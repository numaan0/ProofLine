"""Follow-up photos: attach to an open request, re-check that one requirement, leave the rest alone."""
import asyncio

from PIL import Image
from sqlalchemy import select

import app.services.agent.orchestrator as orch_mod
from app.guardrails.errors import ErrorCode
from app.models.inspection_models import FollowUpRequest, Inspection, InspectionImage, Task
from app.services.meta_client import ModelError, meta_client
from tests.conftest import TEST_DEVICE
from tests.test_inspections_api import client, png_bytes  # noqa: F401  (fixture reuse)
from tests.test_orchestrator import PLAN, fetch, make_inspection, scripted_chat_json

FIRST_PASS = [
    {"image_class": "USABLE", "observations": [
        {"text": "Right outlet has no cover plate", "task_ids": ["T1"], "object_phrase": ""}]},
    {"image_class": "IRRELEVANT", "observations": []},
]
FIRST_VERDICT = {"tasks": [
    {"task_id": "T1", "status": "MISSING", "reasoning": "One outlet has no plate.", "observation_ids": ["O1"]},
    {"task_id": "T2", "status": "CANT_TELL", "reasoning": "Wall not shown.", "observation_ids": [],
     "follow_up_request": "Photograph the full repainted wall."},
]}


def inspection_waiting_for_wall_photo(temp_db, tmp_path, monkeypatch):
    """Run a first pass that leaves 'Repaint the wall' open, then attach one follow-up photo."""
    insp_id = make_inspection(temp_db, tmp_path)
    monkeypatch.setattr(meta_client, "chat_json", scripted_chat_json(PLAN, FIRST_PASS, FIRST_VERDICT))
    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))

    path = tmp_path / "wall.png"
    Image.new("RGB", (200, 150), "white").save(path)

    async def attach():
        async with temp_db() as s:
            wall = (await s.execute(select(Task).where(Task.description == "Repaint the wall"))).scalars().one()
            img = InspectionImage(inspection_id=insp_id, storage_path=str(path), validation_state="VALID", filename="wall.png")
            s.add(img)
            await s.flush()
            fu = (await s.execute(select(FollowUpRequest).where(FollowUpRequest.task_id == wall.id))).scalars().one()
            fu.status, fu.linked_follow_up_image_ids = "CHECKING", [img.id]
            (await s.get(Inspection, insp_id)).status = "REVERIFYING"
            await s.commit()
            return wall.id, img.id

    task_id, img_id = asyncio.run(attach())
    return insp_id, task_id, img_id


def recheck_replies(analysis, verdict):
    async def fake(prompt, image_paths=(), max_tokens=0):
        if "visual evidence step" in prompt:
            return analysis
        if "verification step" in prompt:
            if isinstance(verdict, Exception):
                raise verdict
            return verdict
        raise AssertionError("unexpected prompt")
    return fake


def test_follow_up_photo_resolves_only_that_requirement(temp_db, tmp_path, monkeypatch):
    insp_id, task_id, img_id = inspection_waiting_for_wall_photo(temp_db, tmp_path, monkeypatch)
    seen_by_verifier = []
    analysis = {"image_class": "USABLE", "observations": [
        {"text": "The whole wall is evenly painted with no patches", "task_ids": ["T1"], "object_phrase": ""}]}
    verdict = {"tasks": [{"task_id": "T1", "status": "DONE", "reasoning": "The new photo shows an even coat.",
                          "observation_ids": ["O1"]}]}
    replies = recheck_replies(analysis, verdict)

    async def spy(prompt, image_paths=(), max_tokens=0):
        if "verification step" in prompt:
            seen_by_verifier.append(prompt)
        return await replies(prompt, image_paths, max_tokens)

    monkeypatch.setattr(meta_client, "chat_json", spy)
    asyncio.run(orch_mod.orchestrator.recheck_task(insp_id, task_id, [img_id]))
    insp, tasks, links, fus, notes, imgs = fetch(temp_db, insp_id)

    by_desc = {t.description: t for t in tasks}
    assert by_desc["Repaint the wall"].status == "DONE"
    assert by_desc["Install two outlet covers"].status == "MISSING", "other requirements must not change"
    assert [f.status for f in fus] == ["RESOLVED"] and fus[0].last_error is None
    assert {l.task_id for l in links} == {by_desc["Repaint the wall"].id, by_desc["Install two outlet covers"].id}
    assert insp.status == "COMPLETED" and insp.overall_outcome == "ATTENTION_REQUIRED"
    assert notes[-1].type == "FOLLOW_UP_CHECKED"
    assert insp.agent_trace[-1]["tool"] == "follow_up_check" and insp.agent_trace[-1]["result"] == "DONE"
    assert "Install two outlet covers" not in seen_by_verifier[0], "only the open requirement is re-verified"
    assert next(i for i in imgs if i.id == img_id).analysis_state == "ANALYZED"


def test_follow_up_still_unclear_keeps_request_open(temp_db, tmp_path, monkeypatch):
    insp_id, task_id, img_id = inspection_waiting_for_wall_photo(temp_db, tmp_path, monkeypatch)
    analysis = {"image_class": "LOW_QUALITY", "observations": []}
    verdict = {"tasks": [{"task_id": "T1", "status": "DONE", "reasoning": "Looks fine.", "observation_ids": []}]}
    monkeypatch.setattr(meta_client, "chat_json", recheck_replies(analysis, verdict))

    asyncio.run(orch_mod.orchestrator.recheck_task(insp_id, task_id, [img_id]))
    insp, tasks, _, fus, _, _ = fetch(temp_db, insp_id)
    assert next(t for t in tasks if t.id == task_id).status == "CANT_TELL", "uncited DONE is still downgraded"
    assert fus[0].status == "PENDING" and fus[0].request_text
    assert insp.status == "NEEDS_USER_ACTION"


def test_follow_up_model_outage_keeps_previous_result(temp_db, tmp_path, monkeypatch):
    insp_id, task_id, img_id = inspection_waiting_for_wall_photo(temp_db, tmp_path, monkeypatch)
    analysis = {"image_class": "USABLE", "observations": [{"text": "Painted wall", "task_ids": ["T1"]}]}
    monkeypatch.setattr(meta_client, "chat_json", recheck_replies(analysis, ModelError(ErrorCode.MODEL_TIMEOUT, "slow")))

    asyncio.run(orch_mod.orchestrator.recheck_task(insp_id, task_id, [img_id]))
    insp, tasks, _, fus, notes, _ = fetch(temp_db, insp_id)
    task = next(t for t in tasks if t.id == task_id)
    assert task.status == "CANT_TELL" and task.reasoning == "Wall not shown."
    assert fus[0].status == "PENDING" and "MODEL_TIMEOUT" in fus[0].last_error
    assert insp.status == "NEEDS_USER_ACTION" and insp.error_code is None, "a failed re-check is not a failed inspection"
    assert notes[-1].type == "FOLLOW_UP_FAILED"


def seed_open_follow_up(temp_db, status="NEEDS_USER_ACTION", fu_status="PENDING"):
    async def go():
        async with temp_db() as s:
            insp = Inspection(work_order_text="Repaint the wall", status=status, device_id=TEST_DEVICE)
            s.add(insp)
            await s.flush()
            task = Task(inspection_id=insp.id, description="Repaint the wall", status="CANT_TELL")
            s.add(task)
            await s.flush()
            s.add(FollowUpRequest(inspection_id=insp.id, task_id=task.id, request_text="Photograph the wall.", status=fu_status))
            await s.commit()
            return insp.id, task.id
    return asyncio.run(go())


def test_api_accepts_follow_up_and_schedules_recheck(client, temp_db, monkeypatch):  # noqa: F811
    calls = []

    async def fake_recheck(*args):
        calls.append(args)

    monkeypatch.setattr(orch_mod.orchestrator, "recheck_task", fake_recheck)
    insp_id, task_id = seed_open_follow_up(temp_db)
    r = client.post(f"/api/inspections/{insp_id}/tasks/{task_id}/follow-up-photos",
                    files=[("files", ("wall.png", png_bytes(), "image/png"))])
    assert r.status_code == 202, r.text
    assert calls and calls[0][:2] == (insp_id, task_id)

    report = client.get(f"/api/inspections/{insp_id}/report").json()
    assert report["status"] == "REVERIFYING"
    fu = report["tasks"][0]["follow_up"]
    assert fu["status"] == "CHECKING" and fu["needed"] and fu["image_ids"] == r.json()["image_ids"]
    assert report["images"][0]["follow_up_for"] == task_id


def test_api_rejects_follow_up_when_not_open(client, temp_db):  # noqa: F811
    busy_id, busy_task = seed_open_follow_up(temp_db, status="REVERIFYING", fu_status="CHECKING")
    r = client.post(f"/api/inspections/{busy_id}/tasks/{busy_task}/follow-up-photos",
                    files=[("files", ("wall.png", png_bytes(), "image/png"))])
    assert r.status_code == 409

    insp_id, task_id = seed_open_follow_up(temp_db)
    assert client.post(f"/api/inspections/{insp_id}/tasks/{task_id}/follow-up-photos").status_code == 400
    bad = client.post(f"/api/inspections/{insp_id}/tasks/{task_id}/follow-up-photos",
                      files=[("files", ("x.jpg", b"not an image", "image/jpeg"))])
    assert bad.status_code == 422 and bad.json()["errors"][0]["code"] == "CORRUPT_IMAGE"
    other_id, _ = seed_open_follow_up(temp_db)
    assert client.post(f"/api/inspections/{other_id}/tasks/{task_id}/follow-up-photos",
                       files=[("files", ("wall.png", png_bytes(), "image/png"))]).status_code == 404
