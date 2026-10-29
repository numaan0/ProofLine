"""Investigation tool loop, run through the orchestrator with the Meta API scripted."""
import asyncio
import json

import app.services.agent.investigator as inv_mod
import app.services.agent.orchestrator as orch_mod
from app.guardrails.errors import ErrorCode
from app.services.meta_client import ModelError, meta_client

from .test_orchestrator import PLAN, fetch, make_inspection, scripted_chat_json

SAM_TWO = ("<0f>0<|box;x1=769;y1=499;x2=951;y2=907;w=1920;h=1280;c=0.93|>"
           "<0f>1<|box;x1=1219;y1=495;x2=1462;y2=980;w=1920;h=1280;c=0.9|>")

# First pass: both requirements unresolved.
ANALYSES = [{"image_class": "USABLE", "observations": [
    {"text": "Two wall plates are partly visible at the edge of the frame", "task_ids": ["T1"], "object_phrase": ""}]}]
UNRESOLVED = {"tasks": [
    {"task_id": "T1", "status": "CANT_TELL", "reasoning": "Plates are at the frame edge.", "observation_ids": ["O1"],
     "follow_up_request": "Photograph both outlets straight on."},
    {"task_id": "T2", "status": "CANT_TELL", "reasoning": "Wall not shown.", "observation_ids": [],
     "follow_up_request": "Photograph the repainted wall."},
]}


def call(name, args, id_="c1"):
    return {"id": id_, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def scripted_chat(turns_by_task):
    """turns_by_task: {"T1": [message, message, ...]}; the requirement alias is read from the prompt."""
    queues = {k: list(v) for k, v in turns_by_task.items()}
    seen_tools = []

    async def fake(messages, tools=None, max_tokens=0, model=""):
        seen_tools.append(sorted(t["function"]["name"] for t in tools or []))
        alias = messages[1]["content"].split(":", 1)[0].replace("Requirement ", "")
        queue = queues.get(alias) or []
        return queue.pop(0) if queue else {"role": "assistant", "content": "done"}

    fake.seen_tools = seen_tools
    return fake


def setup(temp_db, tmp_path, monkeypatch, chat, segment_text=SAM_TWO):
    insp_id = make_inspection(temp_db, tmp_path, n_images=1)
    monkeypatch.setattr(meta_client, "chat_json", scripted_chat_json(PLAN, ANALYSES, UNRESOLVED))
    monkeypatch.setattr(meta_client, "chat", chat)
    sam_prompts = []

    async def fake_segment(path, prompt):
        sam_prompts.append(prompt)
        if isinstance(segment_text, Exception):
            raise segment_text
        return segment_text

    monkeypatch.setattr(meta_client, "segment", fake_segment)
    return insp_id, sam_prompts


def test_count_objects_then_finalize_resolves_requirement(temp_db, tmp_path, monkeypatch):
    chat = scripted_chat({"T1": [
        {"role": "assistant", "content": None, "tool_calls": [call("count_objects", {"photo": "P1", "object_phrase": "outlet cover plate"})]},
        {"role": "assistant", "content": None, "tool_calls": [call("finalize", {
            "status": "DONE", "reasoning": "SAM located two cover plates in photo 1 (O2).", "observation_ids": ["O2"]}, "c2")]},
    ]})
    insp_id, sam_prompts = setup(temp_db, tmp_path, monkeypatch, chat)

    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, tasks, links, fus, notes, _ = fetch(temp_db, insp_id)
    by_desc = {t.description: t for t in tasks}
    t1 = by_desc["Install two outlet covers"]

    assert t1.status == "DONE"
    assert t1.reasoning == "SAM located two cover plates in photo 1."
    assert sam_prompts == ["outlet cover plate"], "grounding must reuse the investigation's SAM result"
    [link] = [l for l in links if l.task_id == t1.id]
    assert len(link.region) == 2 and link.region_source == "sam-3.1"
    assert by_desc["Repaint the wall"].status == "CANT_TELL"
    assert [f.task_id for f in fus] == [by_desc["Repaint the wall"].id]
    assert [s["tool"] for s in insp.agent_trace if s["task_id"] == t1.id] == ["count_objects", "finalize"]
    assert insp.agent_trace[0]["result"] == "2 found"
    assert chat.seen_tools[0] == ["count_objects", "finalize", "look_closer"]


def test_invalid_arguments_are_recoverable(temp_db, tmp_path, monkeypatch):
    chat = scripted_chat({"T1": [
        {"role": "assistant", "tool_calls": [call("count_objects", {"photo": "P9", "object_phrase": "outlet"}),
                                             call("delete_files", {}, "c2"),
                                             call("look_closer", {"photo": "P1", "question": "?"}, "c3")]},
        {"role": "assistant", "tool_calls": [call("finalize", {
            "status": "CANT_TELL", "reasoning": "Plates are cut off.", "follow_up_request": "Photograph both outlets."}, "c4")]},
    ]})
    insp_id, sam_prompts = setup(temp_db, tmp_path, monkeypatch, chat)

    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, tasks, *_ = fetch(temp_db, insp_id)
    t1 = next(t for t in tasks if t.description == "Install two outlet covers")
    steps = [s for s in insp.agent_trace if s["task_id"] == t1.id and s["tool"] != "finalize"]
    assert [s["ok"] for s in steps] == [False, False, False]
    assert "Unknown photo 'P9'" in steps[0]["result"]
    assert "Unknown tool 'delete_files'" in steps[1]["result"]
    assert "question" in steps[2]["result"]
    assert sam_prompts == []
    assert insp.status == "NEEDS_USER_ACTION"


def test_done_citing_invented_observation_is_downgraded(temp_db, tmp_path, monkeypatch):
    chat = scripted_chat({"T1": [
        {"role": "assistant", "tool_calls": [call("finalize", {"status": "DONE", "reasoning": "Looks done.", "observation_ids": ["O99"]})]},
    ]})
    insp_id, _ = setup(temp_db, tmp_path, monkeypatch, chat)

    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, tasks, *_ = fetch(temp_db, insp_id)
    assert all(t.status == "CANT_TELL" for t in tasks)
    assert "downgraded" in insp.agent_trace[0]["result"]


def test_tool_budget_is_enforced(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(inv_mod, "MAX_TOOL_CALLS", 2)
    greedy = {"role": "assistant", "tool_calls": [call("count_objects", {"photo": "P1", "object_phrase": "outlet"}, f"c{i}") for i in range(3)]}
    chat = scripted_chat({"T1": [greedy, greedy], "T2": [greedy]})
    insp_id, sam_prompts = setup(temp_db, tmp_path, monkeypatch, chat)

    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, *_ = fetch(temp_db, insp_id)
    assert len(sam_prompts) == 2
    assert any("budget exhausted" in s["result"] for s in insp.agent_trace)
    assert insp.status == "NEEDS_USER_ACTION"


def test_model_outage_in_loop_keeps_first_pass_result(temp_db, tmp_path, monkeypatch):
    async def down(messages, tools=None, max_tokens=0, model=""):
        raise ModelError(ErrorCode.MODEL_RATE_LIMIT, "429")

    insp_id, _ = setup(temp_db, tmp_path, monkeypatch, down)
    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, tasks, links, fus, *_ = fetch(temp_db, insp_id)
    assert insp.status == "NEEDS_USER_ACTION", "investigation is optional; an outage must not fail the inspection"
    assert all(t.status == "CANT_TELL" for t in tasks)
    assert len(fus) == 2
    assert insp.agent_trace[0]["result"] == "Model unavailable: MODEL_RATE_LIMIT"


def test_sam_failure_inside_tool_is_reported_to_model(temp_db, tmp_path, monkeypatch):
    chat = scripted_chat({"T1": [
        {"role": "assistant", "tool_calls": [call("count_objects", {"photo": "P1", "object_phrase": "outlet cover plate"})]},
        {"role": "assistant", "tool_calls": [call("finalize", {"status": "CANT_TELL", "reasoning": "Could not count.",
                                                                "follow_up_request": "Photograph both outlets."}, "c2")]},
    ]})
    insp_id, _ = setup(temp_db, tmp_path, monkeypatch, chat, segment_text=ModelError(ErrorCode.MODEL_TIMEOUT, "slow"))
    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))
    insp, *_ = fetch(temp_db, insp_id)
    assert insp.agent_trace[0]["ok"] is False and "MODEL_TIMEOUT" in insp.agent_trace[0]["result"]
