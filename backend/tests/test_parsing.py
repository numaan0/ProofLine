import asyncio

import pytest

from app.services.agent.planner import validate_plan
from app.services.agent.verifier import DEFAULT_FOLLOW_UP, reconcile
from app.services.agent.visual_analyst import validate_analysis
from app.services.meta_client import MetaClient, ModelError, extract_json
from app.services.segmentation import clean_prompt, parse_boxes

# Real SAM 3.1 output shape captured by scripts/smoke_meta.py (mask payload shortened).
SAM_TEXT = ("<0f>0<|box;x1=769;y1=499;x2=951;y2=907;w=1920;h=1280;c=0.93|><|mask;x=0;y=0;data=122,376,~...|>"
            "<0f>1<|box;x1=10;y1=10;x2=5000;y2=20;w=1920;h=1280|>")


def test_parse_boxes_keeps_valid_and_drops_out_of_bounds():
    regions = parse_boxes(SAM_TEXT, "outlet cover plate")
    assert len(regions) == 1
    r = regions[0]
    assert r["box"] == {"x1": 769, "y1": 499, "x2": 951, "y2": 907}
    assert (r["image_width"], r["image_height"]) == (1920, 1280)
    assert r["confidence"] == pytest.approx(0.93)
    assert r["source"] == "sam-3.1"


def test_parse_boxes_empty():
    assert parse_boxes("", "x") == []
    assert parse_boxes("no detections", "x") == []


def test_clean_prompt_strips_token_syntax():
    assert clean_prompt("<|box;x1=1|> outlet") == "box x1 1 outlet"
    assert len(clean_prompt("a" * 200)) == 60


def test_extract_json_handles_fences_and_prose():
    assert extract_json('Sure:\n```json\n{"a": [1]}\n```') == {"a": [1]}
    assert extract_json("[1, 2]") == [1, 2]


@pytest.mark.parametrize("text", ["", "no json here", "{broken"])
def test_extract_json_raises_model_error(text):
    with pytest.raises(ModelError):
        extract_json(text)


def test_chat_truncated_by_reasoning_raises():
    client = MetaClient(api_key="test")

    async def fake_post(path, body):
        return {"choices": [{"finish_reason": "length", "message": {"content": None}}]}

    client._post = fake_post
    with pytest.raises(ModelError):
        asyncio.run(client.chat([{"role": "user", "content": "hi"}]))


def test_missing_key_is_auth_error():
    with pytest.raises(ModelError) as exc:
        MetaClient(api_key="")._headers()
    assert exc.value.code.value == "MODEL_AUTH_FAILURE"
    assert exc.value.retryable is False


def test_validate_plan():
    tasks = validate_plan({"tasks": [{"description": "Install two outlet covers", "observable_criteria": ""}, {"description": ""}, "junk"]})
    assert tasks == [{"description": "Install two outlet covers", "observable_criteria": "Install two outlet covers"}]
    with pytest.raises(ModelError):
        validate_plan({"tasks": []})
    with pytest.raises(ModelError):
        validate_plan({"nope": 1})


def test_validate_analysis_filters_unknown_tasks():
    out = validate_analysis({"image_class": "weird", "observations": [
        {"text": "Cover plate on left outlet", "task_ids": ["T1", "T9", 3], "object_phrase": "outlet cover plate"},
        {"text": "  "},
    ]}, {"T1", "T2"})
    assert out["image_class"] == "USABLE"
    assert len(out["observations"]) == 1
    assert out["observations"][0]["task_aliases"] == ["T1"]


class TestReconcile:
    def test_done_without_evidence_is_downgraded(self):
        out = reconcile(["T1"], {"O1"}, {"tasks": [{"task_id": "T1", "status": "DONE", "reasoning": "Looks good", "observation_ids": []}]})
        assert out["T1"]["status"] == "CANT_TELL"
        assert out["T1"]["downgraded"] is True
        assert out["T1"]["follow_up_request"] == DEFAULT_FOLLOW_UP

    def test_invented_observation_ids_are_dropped(self):
        out = reconcile(["T1"], {"O1"}, {"tasks": [{"task_id": "T1", "status": "MISSING", "observation_ids": ["O7"]}]})
        assert out["T1"]["status"] == "CANT_TELL"
        assert out["T1"]["observation_aliases"] == []

    def test_unassessed_task_and_unknown_task(self):
        out = reconcile(["T1", "T2"], {"O1"}, {"tasks": [
            {"task_id": "T1", "status": "DONE", "observation_ids": ["O1"], "reasoning": "Plate visible"},
            {"task_id": "T99", "status": "DONE", "observation_ids": ["O1"]},
        ]})
        assert set(out) == {"T1", "T2"}
        assert out["T1"]["status"] == "DONE" and out["T1"]["follow_up_request"] == ""
        assert out["T2"]["status"] == "CANT_TELL"

    def test_invalid_status(self):
        out = reconcile(["T1"], {"O1"}, {"tasks": [{"task_id": "T1", "status": "PROBABLY", "observation_ids": ["O1"]}]})
        assert out["T1"]["status"] == "CANT_TELL"

    def test_malformed_output_raises(self):
        with pytest.raises(ModelError):
            reconcile(["T1"], set(), {"result": "ok"})


def test_humanize_refs_removes_internal_aliases():
    from app.services.agent.verifier import humanize_refs

    raw = ("P1 shows only one outlet with installed white cover plate (O1) while the adjacent box "
           "has no cover plate (O2, O3); O4 notes T2 is out of frame.")
    assert humanize_refs(raw) == ("Photo 1 shows only one outlet with installed white cover plate while the adjacent box "
                                  "has no cover plate; an observation notes this requirement is out of frame.")


def test_parse_boxes_drops_whole_frame_detections():
    whole = "<0f>0<|box;x1=0;y1=0;x2=1919;y2=1279;w=1920;h=1280;c=0.5|>"
    assert parse_boxes(whole, "wall paint surface") == []


def test_reasoning_cutoff_retries_once_with_bigger_budget(monkeypatch):
    import asyncio
    import pytest
    from app.services.meta_client import RETRY_MAX_TOKENS, MetaClient, ModelError

    client = MetaClient.__new__(MetaClient)  # skip key loading; _post is stubbed
    budgets = []

    def stub(replies):
        async def post(path, body):
            budgets.append(body["max_tokens"])
            return replies.pop(0)
        return post

    cut = {"choices": [{"finish_reason": "length", "message": {"content": None}}]}
    ok = {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}
    client._post = stub([cut, ok])
    assert asyncio.run(client.chat([{"role": "user", "content": "hi"}]))["content"] == "{}"
    assert budgets == [4000, RETRY_MAX_TOKENS]

    budgets.clear()
    client._post = stub([cut, cut])
    with pytest.raises(ModelError):
        asyncio.run(client.chat([{"role": "user", "content": "hi"}]))
    assert budgets == [4000, RETRY_MAX_TOKENS], "retries exactly once"


def test_invalid_json_gets_one_corrective_retry():
    import asyncio
    import pytest
    from app.services.meta_client import MetaClient, ModelError

    client = MetaClient.__new__(MetaClient)
    sent = []

    def stub(replies):
        async def chat(messages, tools=None, max_tokens=0, model=""):
            sent.append(list(messages))
            return {"content": replies.pop(0)}
        return chat

    client.chat = stub(["Sure! Here is the plan.", '{"tasks": []}'])
    assert asyncio.run(client.chat_json("plan this")) == {"tasks": []}
    assert len(sent) == 2 and "not valid JSON" in sent[1][-1]["content"]

    sent.clear()
    client.chat = stub(["nope", "still nope"])
    with pytest.raises(ModelError):
        asyncio.run(client.chat_json("plan this"))
    assert len(sent) == 2, "retries exactly once"


def test_transient_provider_error_retried_once(monkeypatch):
    import asyncio
    import httpx
    import pytest
    import app.services.meta_client as mc

    monkeypatch.setattr(mc, "RETRY_DELAY_S", 0)
    codes = []

    def transport(statuses):
        def handler(request):
            code = statuses.pop(0)
            codes.append(code)
            return httpx.Response(code, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})
        return httpx.MockTransport(handler)

    real_client = httpx.AsyncClient
    client = mc.MetaClient.__new__(mc.MetaClient)
    client.base_url, client.timeout, client._headers = "https://example.test", 5, lambda: {}

    monkeypatch.setattr(mc.httpx, "AsyncClient", lambda **kw: real_client(transport=transport_ref[0], **kw))
    transport_ref = [transport([503, 200])]
    assert asyncio.run(client._post("/chat/completions", {}))["choices"]
    assert codes == [503, 200]

    codes.clear()
    transport_ref[0] = transport([503, 503])
    with pytest.raises(mc.ModelError):
        asyncio.run(client._post("/chat/completions", {}))
    assert codes == [503, 503], "retries exactly once"

    codes.clear()
    transport_ref[0] = transport([401])
    with pytest.raises(mc.ModelError):
        asyncio.run(client._post("/chat/completions", {}))
    assert codes == [401], "auth errors are not retried"
