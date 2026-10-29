"""Bundled demo photos from data/samples, so the app can be tried without bringing your own."""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data"))
SAMPLES_DIR = os.path.join(DATA_DIR, "samples")
EVAL_DIR = os.path.join(DATA_DIR, "eval")

DEMO_WORK_ORDER = "- Install cover plates on both wall outlets\n- Install a smoke detector on the hallway ceiling"
BEFORE_AFTER_WORK_ORDER = "- Patch the hole in the living room wall next to the outlet\n- Repaint the living room wall sage green"
# Fixed allowlists: names are never joined from user input.
SAMPLES = {
    "outlets_one_uncovered.png": "completion",
    "hallway_smoke_detector.png": "follow_up",
}
BEFORE_AFTER_SAMPLES = {
    "wall_before_damaged.png": "before",
    "wall_painted_even.png": "after",
}


def _listing(samples: dict) -> list:
    return [{"name": n, "role": role, "url": f"/api/samples/{n}"} for n, role in samples.items()]


@router.get("/samples")
async def list_samples():
    return {"work_order_text": DEMO_WORK_ORDER, "photos": _listing(SAMPLES),
            "before_after": {"work_order_text": BEFORE_AFTER_WORK_ORDER, "photos": _listing(BEFORE_AFTER_SAMPLES)}}


def _case_photo_paths(cases: list) -> dict:
    """Photo name -> file, for every photo the labelled cases use ("sample:" refs live in data/samples)."""
    paths = {}
    for case in cases:
        for ref in case.get("before_photos", []) + case["photos"]:
            name = ref.split(":", 1)[-1]
            folder = SAMPLES_DIR if ref.startswith("sample:") else os.path.join(EVAL_DIR, "photos")
            paths[name] = os.path.join(folder, name + ".png")
    return paths


def _load_cases() -> list:
    with open(os.path.join(EVAL_DIR, "cases.json"), encoding="utf-8") as f:
        return json.load(f)["cases"]


@router.get("/samples/cases")
async def list_case_samples():
    """The labelled evaluation cases (data/eval/cases.json), each loadable as a sample job."""
    def photo(ref: str, role: str) -> dict:
        name = ref.split(":", 1)[-1]
        return {"name": f"{name}.png", "role": role, "url": f"/api/samples/cases/{name}"}

    return {"cases": [{
        "id": c["id"],
        "title": c["id"].split("-", 1)[-1].replace("-", " ").capitalize(),
        "work_order_text": c["work_order"],
        "photos": [photo(r, "before") for r in c.get("before_photos", [])] + [photo(r, "after") for r in c["photos"]],
        "expected": [e["status"] for e in c["expect"]],
    } for c in _load_cases()]}


@router.get("/samples/cases/{name}")
async def get_case_photo(name: str):
    path = _case_photo_paths(_load_cases()).get(name)  # allowlist: only names the cases reference
    if not path or not os.path.isfile(path):
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Sample not found."})
    return FileResponse(path, media_type="image/png")


@router.get("/samples/{name}")
async def get_sample(name: str):
    path = os.path.join(SAMPLES_DIR, name)
    if (name not in SAMPLES and name not in BEFORE_AFTER_SAMPLES) or not os.path.isfile(path):
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Sample not found."})
    return FileResponse(path, media_type="image/png")
