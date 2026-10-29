import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.api.inspections as api_mod
from app.guardrails.config import config
from app.device import DEVICE_COOKIE
from app.main import app
from tests.conftest import TEST_DEVICE


def png_bytes(size=(200, 150)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def client(temp_db, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "enable_semantic_preflight", False)
    monkeypatch.setattr(api_mod, "UPLOAD_DIR", str(tmp_path))
    runs = []

    async def fake_run(inspection_id):
        runs.append(inspection_id)

    monkeypatch.setattr(api_mod.orchestrator, "run_inspection", fake_run)
    with TestClient(app, cookies={DEVICE_COOKIE: TEST_DEVICE}) as c:
        c.runs = runs
        yield c


def test_create_inspection_accepts_and_queues(client):
    r = client.post("/api/inspections", data={"work_order_text": "Install two outlet covers"},
                    files=[("files", ("a.png", png_bytes(), "image/png")), ("files", ("b.png", png_bytes(), "image/png"))])
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "QUEUED" and client.runs == [body["inspection_id"]]

    report = client.get(f"/api/inspections/{body['inspection_id']}/report").json()
    assert len(report["images"]) == 2
    assert report["images"][0]["width"] == 200
    img = client.get(report["images"][0]["url"])
    assert img.status_code == 200 and img.content.startswith(b"\x89PNG")


def test_every_bad_file_is_reported(client):
    r = client.post("/api/inspections", data={"work_order_text": "Install two outlet covers"},
                    files=[("files", ("ok.png", png_bytes(), "image/png")),
                           ("files", ("fake.jpg", b"not an image", "image/jpeg")),
                           ("files", ("tiny.png", png_bytes((10, 10)), "image/png"))])
    assert r.status_code == 422
    errors = r.json()["errors"]
    assert [(e["file_id"], e["code"]) for e in errors] == [("upload_02", "CORRUPT_IMAGE"), ("upload_03", "IMAGE_TOO_SMALL")]
    assert client.runs == []


def test_empty_work_order_rejected_before_anything(client):
    r = client.post("/api/inspections", data={"work_order_text": "  "}, files=[("files", ("a.png", png_bytes(), "image/png"))])
    assert r.status_code == 400 and r.json()["error"]["code"] == "EMPTY_WORK_ORDER"


def test_no_files(client):
    r = client.post("/api/inspections", data={"work_order_text": "Install two outlet covers"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "NO_FILES_UPLOADED"


def test_preflight_outage_is_503_not_rejection(client, monkeypatch):
    from app.services.meta_client import ModelError, meta_client
    from app.guardrails.errors import ErrorCode

    monkeypatch.setattr(config, "enable_semantic_preflight", True)

    async def down(*a, **k):
        raise ModelError(ErrorCode.MODEL_TIMEOUT, "slow")

    monkeypatch.setattr(meta_client, "chat_json", down)
    r = client.post("/api/inspections", data={"work_order_text": "Install two outlet covers"},
                    files=[("files", ("a.png", png_bytes(), "image/png"))])
    assert r.status_code == 503 and r.json()["error"]["code"] == "VALIDATION_SERVICE_FAILURE"


def test_image_from_other_inspection_is_404(client):
    r = client.post("/api/inspections", data={"work_order_text": "Install two outlet covers"},
                    files=[("files", ("a.png", png_bytes(), "image/png"))])
    report = client.get(f"/api/inspections/{r.json()['inspection_id']}/report").json()
    image_id = report["images"][0]["id"]
    assert client.get(f"/api/inspections/ins_other/images/{image_id}").status_code == 404


def test_unknown_inspection_404(client):
    assert client.get("/api/inspections/ins_nope").status_code == 404


def test_retry_only_failed_and_starts_clean(client, temp_db):
    import asyncio
    from sqlalchemy import select
    from app.models.inspection_models import Inspection, Observation, Task

    r = client.post("/api/inspections", data={"work_order_text": "Install two outlet covers"},
                    files=[("files", ("a.png", png_bytes(), "image/png"))])
    iid = r.json()["inspection_id"]
    assert client.post(f"/api/inspections/{iid}/retry").status_code == 409, "queued inspections are not retryable"

    async def fail_with_partial_rows():
        async with temp_db() as s:
            insp = await s.get(Inspection, iid)
            insp.status, insp.error_code = "FAILED", "MODEL_TIMEOUT"
            task = Task(inspection_id=iid, description="Install two outlet covers", status="PENDING")
            s.add(task)
            s.add(Observation(inspection_id=iid, observation_text="partial"))
            await s.commit()

    asyncio.run(fail_with_partial_rows())
    r = client.post(f"/api/inspections/{iid}/retry")
    assert r.status_code == 202 and client.runs == [iid, iid]

    async def state():
        async with temp_db() as s:
            insp = await s.get(Inspection, iid)
            tasks = (await s.execute(select(Task).where(Task.inspection_id == iid))).scalars().all()
            obs = (await s.execute(select(Observation).where(Observation.inspection_id == iid))).scalars().all()
            return insp, tasks, obs

    insp, tasks, obs = asyncio.run(state())
    assert insp.status == "QUEUED" and insp.error_code is None
    assert not tasks and not obs


def test_samples_are_served_from_allowlist_only(client):
    listing = client.get("/api/samples").json()
    assert listing["work_order_text"] and {p["role"] for p in listing["photos"]} == {"completion", "follow_up"}
    img = client.get(listing["photos"][0]["url"])
    assert img.status_code == 200 and img.content.startswith(b"\x89PNG")
    pair = listing["before_after"]
    assert pair["work_order_text"] and {p["role"] for p in pair["photos"]} == {"before", "after"}
    for p in pair["photos"]:
        img = client.get(p["url"])
        assert img.status_code == 200 and img.content.startswith(b"\x89PNG")
    assert client.get("/api/samples/work_order_sample.txt").status_code == 404
    assert client.get("/api/samples/..%2F..%2Fbackend%2F.env").status_code == 404


def test_case_samples_cover_every_case_and_only_their_photos(client):
    cases = client.get("/api/samples/cases").json()["cases"]
    assert len(cases) == 31 and all(c["work_order_text"] and c["photos"] and c["expected"] for c in cases)
    before_after = next(c for c in cases if c["id"].startswith("27-"))
    assert [p["role"] for p in before_after["photos"]] == ["before", "after"]
    for url in {p["url"] for c in cases for p in c["photos"]}:  # includes "sample:" photos from data/samples
        img = client.get(url)
        assert img.status_code == 200 and img.content.startswith(b"\x89PNG"), url
    assert client.get("/api/samples/cases/photo_prompts").status_code == 404
    assert client.get("/api/samples/cases/..%2Fcases").status_code == 404


def test_inspections_are_private_to_the_device(client):
    r = client.post("/api/inspections", data={"work_order_text": "Install two outlet covers"},
                    files=[("files", ("a.png", png_bytes(), "image/png"))])
    inspection_id = r.json()["inspection_id"]
    image_url = client.get(f"/api/inspections/{inspection_id}/report").json()["images"][0]["url"]
    assert [i["inspection_id"] for i in client.get("/api/inspections").json()["inspections"]] == [inspection_id]

    with TestClient(app) as other:  # a new browser: no cookie yet
        listing = other.get("/api/inspections")
        assert listing.json()["inspections"] == []
        issued = listing.cookies.get(DEVICE_COOKIE)
        assert issued and issued != TEST_DEVICE
        for path in (f"/api/inspections/{inspection_id}", f"/api/inspections/{inspection_id}/report", image_url):
            assert other.get(path).status_code == 404, path
        assert other.post(f"/api/inspections/{inspection_id}/retry").status_code == 404
        # The cookie is kept, so the device sees its own inspection on the next request.
        mine = other.post("/api/inspections", data={"work_order_text": "Install two outlet covers"},
                          files=[("files", ("a.png", png_bytes(), "image/png"))]).json()["inspection_id"]
        assert [i["inspection_id"] for i in other.get("/api/inspections").json()["inspections"]] == [mine]


def test_bad_device_cookie_is_replaced(client):
    with TestClient(app, cookies={DEVICE_COOKIE: "../not-an-id"}) as c:
        assert c.get("/api/inspections").cookies.get(DEVICE_COOKIE) not in (None, "../not-an-id")
