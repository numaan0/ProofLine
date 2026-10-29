"""End-to-end orchestrator runs with the Meta API mocked out."""
import asyncio
import io

from PIL import Image
from sqlalchemy import select

import app.services.agent.orchestrator as orch_mod
from app.guardrails.errors import ErrorCode
from app.models.inspection_models import EvidenceLink, FollowUpRequest, Inspection, InspectionImage, Notification, Task
from app.services.meta_client import ModelError, meta_client

SAM_TEXT = "<0f>0<|box;x1=1219;y1=495;x2=1462;y2=980;w=1920;h=1280;c=0.8|>"


def make_inspection(session_factory, tmp_path, n_images=2):
    paths = []
    for i in range(n_images):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (200, 150), "white").save(p)
        paths.append(str(p))

    async def create():
        async with session_factory() as s:
            insp = Inspection(work_order_text="Install two outlet covers\nRepaint the wall", status="QUEUED")
            s.add(insp)
            await s.flush()
            for p in paths:
                s.add(InspectionImage(inspection_id=insp.id, storage_path=p, validation_state="VALID", filename="x.png"))
            await s.commit()
            return insp.id

    return asyncio.run(create())


def fetch(session_factory, inspection_id):
    async def go():
        async with session_factory() as s:
            insp = await s.get(Inspection, inspection_id)
            tasks = (await s.execute(select(Task).where(Task.inspection_id == inspection_id))).scalars().all()
            links = (await s.execute(select(EvidenceLink))).scalars().all()
            fus = (await s.execute(select(FollowUpRequest))).scalars().all()
            notes = (await s.execute(select(Notification))).scalars().all()
            imgs = (await s.execute(select(InspectionImage))).scalars().all()
            return insp, tasks, links, fus, notes, imgs

    return asyncio.run(go())


def scripted_chat_json(planner, analyses, verifier):
    """Route calls by prompt content to canned replies; analyses is a list consumed per image."""
    analyses = list(analyses)

    async def fake(prompt, image_paths=(), max_tokens=0):
        if "planning step" in prompt:
            return planner
        if "visual evidence step" in prompt:
            reply = analyses.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        if "verification step" in prompt:
            if isinstance(verifier, Exception):
                raise verifier
            return verifier
        raise AssertionError("unexpected prompt")

    return fake


PLAN = {"tasks": [{"description": "Install two outlet covers", "observable_criteria": "Both outlets have plates"},
                  {"description": "Repaint the wall", "observable_criteria": "Wall evenly painted"}]}


def test_happy_path_links_evidence_and_grounds(temp_db, tmp_path, monkeypatch):
    insp_id = make_inspection(temp_db, tmp_path)
    analyses = [
        {"image_class": "USABLE", "observations": [
            {"text": "Right outlet has no cover plate; open box visible", "task_ids": ["T1"], "object_phrase": "open electrical box"}]},
        {"image_class": "IRRELEVANT", "observations": []},
    ]
    verdict = {"tasks": [
        {"task_id": "T1", "status": "MISSING", "reasoning": "One outlet has no plate.", "observation_ids": ["O1"]},
        {"task_id": "T2", "status": "CANT_TELL", "reasoning": "Wall not shown.", "observation_ids": [],
         "follow_up_request": "Photograph the full repainted wall."},
    ]}
    monkeypatch.setattr(meta_client, "chat_json", scripted_chat_json(PLAN, analyses, verdict))
    sam_calls = []

    async def fake_segment(path, prompt):
        sam_calls.append(prompt)
        return SAM_TEXT

    monkeypatch.setattr(meta_client, "segment", fake_segment)

    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, tasks, links, fus, notes, imgs = fetch(temp_db, insp_id)

    assert insp.status == "NEEDS_USER_ACTION"
    assert insp.overall_outcome == "ATTENTION_REQUIRED"
    by_desc = {t.description: t for t in tasks}
    assert by_desc["Install two outlet covers"].status == "MISSING"
    assert by_desc["Repaint the wall"].status == "CANT_TELL"
    assert len(links) == 1 and links[0].task_id == by_desc["Install two outlet covers"].id
    assert links[0].region[0]["box"]["x1"] == 1219 and links[0].region_source == "sam-3.1"
    assert sam_calls == ["open electrical box"]
    assert [f.request_text for f in fus] == ["Photograph the full repainted wall."]
    assert [n.type for n in notes] == ["FOLLOW_UP_REQUESTED"]
    assert sorted(i.analysis_state for i in imgs) == ["ANALYZED", "IRRELEVANT"]


def test_provider_failure_is_failed_not_cant_tell(temp_db, tmp_path, monkeypatch):
    insp_id = make_inspection(temp_db, tmp_path)
    timeout = ModelError(ErrorCode.MODEL_TIMEOUT, "timed out")
    analyses = [{"image_class": "USABLE", "observations": []}] * 2
    monkeypatch.setattr(meta_client, "chat_json", scripted_chat_json(PLAN, analyses, timeout))

    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, tasks, links, fus, notes, _ = fetch(temp_db, insp_id)

    assert insp.status == "FAILED"
    assert insp.error_code == "MODEL_TIMEOUT"
    assert insp.overall_outcome is None
    assert all(t.status == "PENDING" for t in tasks), "a technical failure must not become a finding"
    assert not links and not fus
    assert [n.type for n in notes] == ["INSPECTION_FAILED"]


def test_all_images_fail_analysis(temp_db, tmp_path, monkeypatch):
    insp_id = make_inspection(temp_db, tmp_path)
    err = ModelError(ErrorCode.MODEL_RATE_LIMIT, "429")
    monkeypatch.setattr(meta_client, "chat_json", scripted_chat_json(PLAN, [err, err], {"tasks": []}))

    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, *_ = fetch(temp_db, insp_id)
    assert insp.status == "FAILED" and insp.error_code == "MODEL_RATE_LIMIT"


def test_invented_references_never_become_done(temp_db, tmp_path, monkeypatch):
    insp_id = make_inspection(temp_db, tmp_path, n_images=1)
    analyses = [{"image_class": "USABLE", "observations": [{"text": "A wall", "task_ids": ["T2"]}]}]
    verdict = {"tasks": [
        {"task_id": "T1", "status": "DONE", "reasoning": "Both plates installed.", "observation_ids": ["O42"]},
        {"task_id": "T2", "status": "DONE", "reasoning": "Wall painted.", "observation_ids": []},
    ]}
    monkeypatch.setattr(meta_client, "chat_json", scripted_chat_json(PLAN, analyses, verdict))
    monkeypatch.setattr(meta_client, "segment", lambda *a: (_ for _ in ()).throw(AssertionError("SAM should not run")))

    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, tasks, links, *_ = fetch(temp_db, insp_id)
    assert all(t.status == "CANT_TELL" for t in tasks)
    assert not links
    assert insp.overall_outcome == "EVIDENCE_INCOMPLETE"


def test_sam_failure_keeps_finding_without_overlay(temp_db, tmp_path, monkeypatch):
    insp_id = make_inspection(temp_db, tmp_path, n_images=1)
    analyses = [{"image_class": "USABLE", "observations": [
        {"text": "Both outlets have white plates", "task_ids": ["T1"], "object_phrase": "outlet cover plate"},
        {"text": "Wall evenly painted", "task_ids": ["T2"], "object_phrase": ""}]}]
    verdict = {"tasks": [
        {"task_id": "T1", "status": "DONE", "reasoning": "Two plates.", "observation_ids": ["O1"]},
        {"task_id": "T2", "status": "DONE", "reasoning": "Even paint.", "observation_ids": ["O2"]},
    ]}
    monkeypatch.setattr(meta_client, "chat_json", scripted_chat_json(PLAN, analyses, verdict))

    async def broken_segment(path, prompt):
        raise ModelError(ErrorCode.MODEL_TIMEOUT, "slow")

    monkeypatch.setattr(meta_client, "segment", broken_segment)
    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, tasks, links, fus, notes, _ = fetch(temp_db, insp_id)
    assert insp.status == "COMPLETED" and insp.overall_outcome == "NO_FLAGGED_ISSUES"
    assert len(links) == 2 and all(l.region is None for l in links)
    assert [n.type for n in notes] == ["INSPECTION_COMPLETED"]
