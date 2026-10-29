"""SAM 3.1 adapter: converts raw segmentation tokens into internal regions.

SAM output is token text, e.g.
  <0f>0<|box;x1=181;y1=365;x2=556;y2=486;w=1516;h=1600;c=0.96|><|mask;x=0;y=0;data=...|>
Boxes are pixel xyxy (x2/y2 inclusive) in the source image's coordinate space.
Mask payloads are not decoded yet (encoding is undocumented); only boxes are kept.
A region means "SAM detected this object here", never "the work is complete".
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from .meta_client import ModelError, meta_client

_BOX = re.compile(r"<\|box;([^|]*)\|>")
MAX_PROMPT_CHARS = 60
# Surface prompts ("wall paint") can come back as a box around the whole frame; that locates nothing.
MAX_AREA_RATIO = 0.6


def parse_boxes(text: str, label: str) -> List[Dict[str, Any]]:
    regions = []
    for match in _BOX.finditer(text or ""):
        fields = dict(kv.split("=", 1) for kv in match.group(1).split(";") if "=" in kv)
        try:
            x1, y1, x2, y2 = (int(float(fields[k])) for k in ("x1", "y1", "x2", "y2"))
            w, h = int(float(fields["w"])), int(float(fields["h"]))
        except (KeyError, ValueError):
            continue
        if not (0 <= x1 <= x2 < w and 0 <= y1 <= y2 < h):
            continue
        if (x2 - x1 + 1) * (y2 - y1 + 1) > MAX_AREA_RATIO * w * h:
            continue
        regions.append({
            "label": label,
            "box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            "image_width": w,
            "image_height": h,
            "confidence": float(fields["c"]) if "c" in fields else None,
            "source": "sam-3.1",
        })
    return regions


def clean_prompt(prompt: str) -> str:
    """SAM expects a short noun phrase; strip anything that looks like box/point tokens."""
    prompt = re.sub(r"[<>|;=]", " ", prompt or "")
    return " ".join(prompt.split())[:MAX_PROMPT_CHARS]


async def segment_object(image_path: str | Path, prompt: str) -> List[Dict[str, Any]]:
    prompt = clean_prompt(prompt)
    if not prompt:
        return []
    text = await meta_client.segment(image_path, prompt)
    return parse_boxes(text, prompt)


__all__ = ["parse_boxes", "clean_prompt", "segment_object", "ModelError"]
