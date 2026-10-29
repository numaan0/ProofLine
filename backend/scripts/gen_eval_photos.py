"""Generate evaluation photos with muse-image-1.0 (one-off; outputs are committed in data/eval/photos).

Plain prompts are generated from scratch. Entries under "_edits" start from an existing photo, so a
before photo shows the same place as its after photo (same wall, window, outlets).
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys

import httpx
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.services.meta_client import _load_api_key, image_data_url  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "eval"))


async def save(client: httpx.AsyncClient, name: str, r: httpx.Response) -> None:
    if r.status_code != 200:
        print("FAIL", name, r.status_code, r.text[:200])
        return
    d = r.json()["data"][0]
    raw = base64.b64decode(d["b64_json"]) if d.get("b64_json") else (await client.get(d["url"])).content
    Image.open(io.BytesIO(raw)).convert("RGB").save(os.path.join(ROOT, "photos", f"{name}.png"), format="PNG", optimize=True)  # API returns WebP
    print("ok", name)


async def generate(client: httpx.AsyncClient, name: str, prompt: str, sem: asyncio.Semaphore, source: str | None = None) -> None:
    if os.path.exists(os.path.join(ROOT, "photos", f"{name}.png")):
        print("skip", name)
        return
    async with sem:
        if source:
            body = {"model": "muse-image-1.0", "n": 1, "prompt": prompt,
                    "images": [{"image_url": image_data_url(os.path.join(ROOT, "photos", f"{source}.png"))}]}
            r = await client.post("/images/edits", json=body)
        else:
            r = await client.post("/images/generations", json={"model": "muse-image-1.0", "n": 1, "prompt": prompt})
    await save(client, name, r)


async def main(only: list[str]) -> None:
    data = json.load(open(os.path.join(ROOT, "photo_prompts.json")))
    prompts = {k: v for k, v in data.items() if not k.startswith("_")}
    edits = data.get("_edits", {})
    sem = asyncio.Semaphore(3)
    async with httpx.AsyncClient(base_url="https://api.meta.ai/v1", timeout=180,
                                 headers={"Authorization": f"Bearer {_load_api_key()}"}) as client:
        # Plain generations first: an edit may start from one of them.
        await asyncio.gather(*(generate(client, n, p, sem) for n, p in prompts.items() if not only or n in only))
        await asyncio.gather(*(generate(client, n, e["prompt"], sem, e["from"]) for n, e in edits.items() if not only or n in only))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
