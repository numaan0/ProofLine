"""Phase 0 smoke tests against the live Meta Model API.

Run from backend/:  .venv/Scripts/python.exe scripts/smoke_meta.py [image_path]

Checks: key + model list, text call, base64 image input, tool-calling loop,
SAM 3.1 segmentation. Never prints the API key.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = BACKEND.parent / "data" / "samples" / "outlets_one_uncovered.png"
BASE_URL = "https://api.meta.ai/v1"
SPARK = "muse-spark-1.3"
SAM = "sam-3.1"
# Muse Spark spends hidden reasoning tokens from max_tokens; small caps return content=None.
REASONING_HEADROOM = 4000


def load_key() -> str:
    env = {**dotenv_values(BACKEND / ".env"), **os.environ}
    key = env.get("MODEL_API_KEY") or env.get("META_API_KEY") or ""
    if not key:
        sys.exit("No MODEL_API_KEY or META_API_KEY configured.")
    return key


def data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def report(name: str, ok: bool, detail: str, started: float) -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name} ({time.time() - started:.1f}s)\n       {detail}\n")
    return ok


def check_models(client: httpx.Client) -> bool:
    t = time.time()
    r = client.get("/models")
    ids = [m["id"] for m in r.json().get("data", [])] if r.status_code == 200 else []
    ok = SPARK in ids and SAM in ids
    return report("models", ok, f"HTTP {r.status_code}; {SPARK}={'yes' if SPARK in ids else 'no'}, {SAM}={'yes' if SAM in ids else 'no'}", t)


def check_text(client: httpx.Client) -> bool:
    t = time.time()
    r = client.post("/chat/completions", json={
        "model": SPARK,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": REASONING_HEADROOM,
    })
    text = r.json()["choices"][0]["message"]["content"] if r.status_code == 200 else r.text[:300]
    return report("text", r.status_code == 200 and "OK" in text, f"HTTP {r.status_code}; reply={text!r}", t)


def check_image(client: httpx.Client, image: Path) -> bool:
    t = time.time()
    r = client.post("/chat/completions", json={
        "model": SPARK,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "How many electrical outlets are visible, and does each have a cover plate? Answer in one sentence."},
            {"type": "image_url", "image_url": {"url": data_url(image)}},
        ]}],
        "max_tokens": REASONING_HEADROOM,
    })
    text = r.json()["choices"][0]["message"]["content"] if r.status_code == 200 else r.text[:300]
    return report("image (base64, chat completions)", r.status_code == 200 and bool(text), f"HTTP {r.status_code}; reply={text!r}", t)


def check_tools(client: httpx.Client) -> bool:
    t = time.time()
    tools = [{"type": "function", "function": {
        "name": "get_task_count",
        "description": "Return how many tasks are in the given inspection.",
        "parameters": {"type": "object", "properties": {"inspection_id": {"type": "string"}}, "required": ["inspection_id"]},
    }}]
    messages = [{"role": "user", "content": "How many tasks are in inspection ins_demo? Use the tool."}]
    calls = []
    for _ in range(4):
        r = client.post("/chat/completions", json={"model": SPARK, "messages": messages, "tools": tools, "tool_choice": "auto", "max_tokens": REASONING_HEADROOM})
        if r.status_code != 200:
            return report("tool calling", False, f"HTTP {r.status_code}; {r.text[:300]}", t)
        choice = r.json()["choices"][0]
        msg = choice["message"]
        if choice.get("finish_reason") != "tool_calls" or not msg.get("tool_calls"):
            ok = bool(calls) and "3" in (msg.get("content") or "")
            return report("tool calling", ok, f"calls={calls}; final={msg.get('content')!r}", t)
        messages.append(msg)
        for tc in msg["tool_calls"]:
            args = json.loads(tc["function"]["arguments"] or "{}")
            calls.append((tc["function"]["name"], args))
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps({"task_count": 3})})
    return report("tool calling", False, f"loop did not terminate; calls={calls}", t)


def check_sam(client: httpx.Client, image: Path, prompt: str = "electrical outlet") -> bool:
    t = time.time()
    body = {
        "model": SAM,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": data_url(image)},
        ]}],
        "stream": True,
        "metadata": {"include_confidence": "true"},
    }
    text, events, status = "", [], None
    with client.stream("POST", "/responses", json=body, headers={"Accept": "text/event-stream"}) as r:
        status = r.status_code
        if status != 200:
            r.read()
            return report("SAM 3.1", False, f"HTTP {status}; {r.text[:300]}", t)
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            events.append(ev.get("type"))
            if ev.get("type") == "response.output_text.delta":
                text += ev.get("delta", "")
    boxes = text.count("<|box;")
    # Keep mask payloads out of the console; show boxes only.
    preview = " ".join(seg for seg in text.split("<|") if seg.startswith("box;"))[:600]
    print(f"       event types: {sorted(set(e for e in events if e))}")
    return report(f"SAM 3.1 ('{prompt}')", boxes > 0, f"HTTP {status}; {boxes} box(es); {len(text)} chars; boxes: {preview}", t)


def main() -> None:
    image = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IMAGE
    client = httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {load_key()}"}, timeout=120)
    results = {}
    for name, fn in [("models", lambda: check_models(client)), ("text", lambda: check_text(client)),
                     ("image", lambda: check_image(client, image)), ("tools", lambda: check_tools(client)),
                     ("sam", lambda: check_sam(client, image))]:
        try:
            results[name] = fn()
        except Exception as e:  # report and continue so one failure doesn't hide others
            results[name] = report(name, False, f"{type(e).__name__}: {e}", time.time())
    print("Summary:", {k: "PASS" if v else "FAIL" for k, v in results.items()})
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
