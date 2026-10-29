"""Before/after photos: compared side by side, never evidence on their own, and a different place blocks a verdict."""
import asyncio

from PIL import Image
from sqlalchemy import select

import app.services.agent.orchestrator as orch_mod
from app.guardrails.errors import ErrorCode
from app.models.inspection_models import FollowUpRequest, Inspection, InspectionImage, Observation, Task
from app.services.agent.comparer import SAME_SPOT_FOLLOW_UP, enforce_same_place, validate_comparisons
from app.services.agent.verifier import reconcile
from app.services.meta_client import ModelError, meta_client
from tests.test_inspections_api import client, png_bytes  # noqa: F401  (fixture reuse)
from tests.test_orchestrator import fetch

PLAN = {"tasks": [{"description": "Patch and repaint the hallway wall", "observable_criteria": "No hole; even paint"}]}
AFTER_ANALYSIS = {"image_class": "USABLE", "observations": [
    {"text": "Wall is evenly painted pale green; no hole visible", "task_ids": ["T1"], "object_phrase": "painted wall"}]}


def comparison(same_place, change="the hole above the outlet is filled and painted"):
    return {"comparisons": [{"task_ids": ["T1"], "before_photo": "P1", "after_photo": "P2", "same_place": same_place,
                             "landmarks": "window and outlet in the same positions", "change": change,
                             "object_phrase": "patched area", "limitations": ""}]}


# --- deterministic rules -------------------------------------------------------------------------

def test_before_photo_alone_never_supports_a_verdict():
    raw = {"tasks": [{"task_id": "T1", "status": "MISSING", "reasoning": "Hole is visible.", "observation_ids": ["O1"]}]}
    out = reconcile(["T1"], {"O1", "O2"}, raw, before_aliases=frozenset({"O1"}))["T1"]
    assert out["status"] == "CANT_TELL" and out["downgraded"]
    assert "before photos" in out["reasoning"]

    raw["tasks"][0]["observation_ids"] = ["O1", "O2"]
    assert reconcile(["T1"], {"O1", "O2"}, raw, before_aliases=frozenset({"O1"}))["T1"]["status"] == "MISSING"


def _obs(alias, image_id, **extra):
    return {"alias": alias, "image_id": image_id, "task_aliases": ["T1"], "taken": "after", **extra}


def test_different_place_blocks_done_unless_another_photo_matches():
    verdict = {"T1": {"status": "DONE", "reasoning": "Wall is painted.", "observation_aliases": ["O1"],
                      "follow_up_request": "", "downgraded": False}}
    observations = [_obs("O1", "img_after"), _obs("O2", "img_after", source="comparison", same_place="NO")]
    out = enforce_same_place(verdict, {o["alias"]: o for o in observations}, observations)["T1"]
    assert out["status"] == "CANT_TELL" and out["follow_up_request"] == SAME_SPOT_FOLLOW_UP

    # A second after photo that does match the before photo can carry the verdict.
    observations += [_obs("O3", "img_after2"), _obs("O4", "img_after2", source="comparison", same_place="YES")]
    verdict["T1"]["observation_aliases"] = ["O1", "O3"]
    assert enforce_same_place(verdict, {o["alias"]: o for o in observations}, observations)["T1"]["status"] == "DONE"


def test_unsure_comparison_does_not_block():
    verdict = {"T1": {"status": "DONE", "reasoning": "ok", "observation_aliases": ["O1"], "follow_up_request": "", "downgraded": False}}
    observations = [_obs("O1", "a"), _obs("O2", "a", source="comparison", same_place="UNSURE")]
    assert enforce_same_place(verdict, {o["alias"]: o for o in observations}, observations)["T1"]["status"] == "DONE"


def test_comparisons_with_wrong_photo_roles_are_dropped():
    raw = {"comparisons": [
        {"task_ids": ["T1"], "before_photo": "P2", "after_photo": "P1", "same_place": "YES", "change": "x"},  # swapped
        {"task_ids": ["T9"], "before_photo": "P1", "after_photo": "P2", "same_place": "YES", "change": "x"},  # unknown task
        {"task_ids": ["T1"], "before_photo": "P1", "after_photo": "P2", "same_place": "maybe", "change": ""},
    ]}
    out = validate_comparisons(raw, {"T1"}, before={"P1"}, after={"P2"})
    assert len(out) == 1 and out[0]["same_place"] == "UNSURE" and out[0]["change"] == "no visible change"


# --- orchestrator ---------------------------------------------------------------------------------

def make_before_after(session_factory, tmp_path):
    async def create():
        async with session_factory() as s:
            insp = Inspection(work_order_text="Patch and repaint the hallway wall", status="QUEUED")
            s.add(insp)
            await s.flush()
            for name, role in (("before.png", "before"), ("after.png", None)):
                Image.new("RGB", (200, 150), "white").save(tmp_path / name)
                s.add(InspectionImage(inspection_id=insp.id, storage_path=str(tmp_path / name), validation_state="VALID",
                                      filename=name, role=role))
                await s.flush()
            await s.commit()
            return insp.id
    return asyncio.run(create())


def scripted(compare_reply, verdict, calls):
    async def fake(prompt, image_paths=(), max_tokens=0):
        if "planning step" in prompt:
            return PLAN
        if "visual evidence step" in prompt:
            calls.append(("analysis", [str(p) for p in image_paths]))
            return AFTER_ANALYSIS
        if "comparison step" in prompt:
            calls.append(("compare", [str(p) for p in image_paths]))
            if isinstance(compare_reply, Exception):
                raise compare_reply
            return compare_reply
        if "verification step" in prompt:
            calls.append(("verify", prompt))
            return verdict
        raise AssertionError("unexpected prompt")
    return fake


def observations_of(session_factory):
    async def go():
        async with session_factory() as s:
            return (await s.execute(select(Observation).order_by(Observation.created_at))).scalars().all()
    return asyncio.run(go())


def test_matching_before_after_supports_the_change(temp_db, tmp_path, monkeypatch):
    insp_id = make_before_after(temp_db, tmp_path)
    calls = []
    verdict = {"tasks": [{"task_id": "T1", "status": "DONE", "reasoning": "The hole is patched and painted.",
                          "observation_ids": ["O1", "O2"]}]}
    monkeypatch.setattr(meta_client, "chat_json", scripted(comparison("YES"), verdict, calls))
    monkeypatch.setattr(meta_client, "segment", lambda *a: asyncio.sleep(0, ""))

    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, tasks, links, fus, notes, imgs = fetch(temp_db, insp_id)

    assert insp.status == "COMPLETED" and tasks[0].status == "DONE"
    analysis_calls = [c for c in calls if c[0] == "analysis"]
    assert len(analysis_calls) == 1 and analysis_calls[0][1][0].endswith("after.png"), "before photos are not analyzed alone"
    compare_paths = next(c[1] for c in calls if c[0] == "compare")
    assert [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in compare_paths] == ["before.png", "after.png"]
    obs = observations_of(temp_db)
    compared = [o for o in obs if (o.meta_data or {}).get("source") == "comparison"]
    assert len(compared) == 1 and compared[0].meta_data["same_place"] == "YES"
    assert compared[0].image_id == next(i.id for i in imgs if i.role is None), "comparison is evidence on the after photo"
    assert compared[0].meta_data["before_image_id"] == next(i.id for i in imgs if i.role == "before")
    assert insp.agent_trace[0]["tool"] == "compare_before_after" and insp.agent_trace[0]["args"]["pairs"] == ["1->2"]
    assert all(i.analysis_state == "ANALYZED" for i in imgs)
    assert '"taken": "after"' in next(c[1] for c in calls if c[0] == "verify")


def test_different_place_turns_done_into_follow_up(temp_db, tmp_path, monkeypatch):
    insp_id = make_before_after(temp_db, tmp_path)
    verdict = {"tasks": [{"task_id": "T1", "status": "DONE", "reasoning": "The wall is painted.", "observation_ids": ["O1"]}]}
    monkeypatch.setattr(meta_client, "chat_json", scripted(comparison("NO", "a different wall with a door"), verdict, []))

    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, tasks, links, fus, notes, imgs = fetch(temp_db, insp_id)

    assert tasks[0].status == "CANT_TELL", "a photo of a different place must not confirm the work"
    assert [f.request_text for f in fus] == [SAME_SPOT_FOLLOW_UP]
    assert insp.status == "NEEDS_USER_ACTION"


def test_comparison_outage_fails_instead_of_ignoring_before_photos(temp_db, tmp_path, monkeypatch):
    insp_id = make_before_after(temp_db, tmp_path)
    monkeypatch.setattr(meta_client, "chat_json",
                        scripted(ModelError(ErrorCode.MODEL_TIMEOUT, "timed out"), {"tasks": []}, []))

    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, tasks, *_ = fetch(temp_db, insp_id)
    assert insp.status == "FAILED" and insp.error_code == "MODEL_TIMEOUT"
    assert all(t.status == "PENDING" for t in tasks)


def test_follow_up_photo_is_compared_with_the_before_photo(temp_db, tmp_path, monkeypatch):
    insp_id = make_before_after(temp_db, tmp_path)
    first = {"tasks": [{"task_id": "T1", "status": "DONE", "reasoning": "Painted.", "observation_ids": ["O1"]}]}
    monkeypatch.setattr(meta_client, "chat_json", scripted(comparison("NO"), first, []))
    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))

    Image.new("RGB", (200, 150), "white").save(tmp_path / "retake.png")

    async def attach():
        async with temp_db() as s:
            task = (await s.execute(select(Task))).scalars().one()
            img = InspectionImage(inspection_id=insp_id, storage_path=str(tmp_path / "retake.png"), validation_state="VALID",
                                  filename="retake.png")
            s.add(img)
            await s.flush()
            fu = (await s.execute(select(FollowUpRequest))).scalars().one()
            fu.status, fu.linked_follow_up_image_ids = "CHECKING", [img.id]
            await s.commit()
            return task.id, img.id

    task_id, img_id = asyncio.run(attach())
    calls = []
    # In the re-check the retake is P3; the verifier sees O1 (old analysis), O2 (old NO comparison), then O3, O4.
    retake = {"comparisons": [{"task_ids": ["T1"], "before_photo": "P1", "after_photo": "P3", "same_place": "YES",
                               "landmarks": "same window", "change": "hole filled and painted", "object_phrase": ""}]}
    second = {"tasks": [{"task_id": "T1", "status": "DONE", "reasoning": "Retake matches the before photo.",
                         "observation_ids": ["O3", "O4"]}]}
    monkeypatch.setattr(meta_client, "chat_json", scripted(retake, second, calls))
    asyncio.run(orch_mod.orchestrator.recheck_task(insp_id, task_id, [img_id]))
    insp, tasks, links, fus, *_ = fetch(temp_db, insp_id)

    assert [c[0] for c in calls] == ["analysis", "compare", "verify"]
    assert tasks[0].status == "DONE" and fus[0].status == "RESOLVED"
    assert {l.image_id for l in links} == {img_id}
    steps = [s for s in insp.agent_trace if s.get("round") == "follow_up"]
    assert [s["tool"] for s in steps] == ["compare_before_after", "follow_up_check"]


# --- API ------------------------------------------------------------------------------------------

def test_api_stores_before_photos_first_with_role(client):  # noqa: F811
    r = client.post("/api/inspections", data={"work_order_text": "Repaint the wall"},
                    files=[("files", ("after.png", png_bytes(), "image/png")),
                           ("before_files", ("before.png", png_bytes(), "image/png"))])
    assert r.status_code == 202
    images = client.get(f"/api/inspections/{r.json()['inspection_id']}/report").json()["images"]
    assert [(i["filename"], i["role"]) for i in images] == [("before.png", "before"), ("after.png", "after")]


def test_api_rejects_before_photos_without_after_photos(client):  # noqa: F811
    r = client.post("/api/inspections", data={"work_order_text": "Repaint the wall"},
                    files=[("before_files", ("before.png", png_bytes(), "image/png"))])
    assert r.status_code == 400 and r.json()["error"]["code"] == "NO_FILES_UPLOADED"
    assert client.runs == []


def test_api_reports_bad_before_photo_by_its_own_id(client):  # noqa: F811
    r = client.post("/api/inspections", data={"work_order_text": "Repaint the wall"},
                    files=[("files", ("after.png", png_bytes(), "image/png")),
                           ("before_files", ("broken.jpg", b"nope", "image/jpeg"))])
    assert r.status_code == 422
    assert [e["file_id"] for e in r.json()["errors"]] == ["before_01"]
