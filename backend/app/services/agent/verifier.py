from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from ...guardrails.errors import ErrorCode
from ..meta_client import ModelError, meta_client

STATUSES = {"DONE", "MISSING", "CANT_TELL"}
DEFAULT_FOLLOW_UP = "Upload a clear, close-up photo of this item taken straight on, with the surrounding area visible."

PROMPT = """You are the verification step of a work-verification tool. Decide each requirement's status
using ONLY the observations listed. Be conservative: a false "DONE" is the worst possible error.

Statuses:
- DONE: observations positively show the requirement is met (all quantities accounted for).
- MISSING: observations positively show it is NOT met (e.g. cover plate absent, wall still damaged).
  Not seeing something is not proof it is missing.
- CANT_TELL: insufficient, obscured, partial, or conflicting evidence.

Observations marked "taken": "before" describe the site BEFORE the work. Use them only to judge what
changed; they can never be the evidence that work is done or not done. If a comparison says an after
photo may not show the same place as the before photo, do not treat that photo as showing the change.

For every requirement give: status, one or two sentences of plain-language reasoning that describe
what was seen (refer to photos as "photo 1", never use IDs like O1 or T1 in the reasoning),
the observation IDs supporting the status, and for CANT_TELL a specific follow_up_request
(which photo to take, from where) based on what is actually missing.

Requirements:
%s

Observations:
%s

Return ONLY JSON:
{"tasks": [{"task_id": "T1", "status": "...", "reasoning": "...", "observation_ids": ["O1"], "follow_up_request": ""}]}"""


_OBS_REF_GROUP = re.compile(r"\s*\((?:O\d+)(?:\s*(?:,|and|&)\s*O\d+)*\)")
_PHOTO_REF = re.compile(r"\bP(\d+)\b")
_BARE_OBS = re.compile(r"\bO\d+\b")
_BARE_TASK = re.compile(r"\bT\d+\b")


def humanize_refs(text: str) -> str:
    """Strip internal aliases (O1, T2, P1) that the model sometimes leaks into user-facing text."""
    text = _OBS_REF_GROUP.sub("", text)
    text = _PHOTO_REF.sub(lambda m: f"photo {m.group(1)}", text)
    text = _BARE_OBS.sub("an observation", text)
    text = _BARE_TASK.sub("this requirement", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:1].upper() + text[1:]


def reconcile(task_aliases: List[str], obs_aliases: set[str], raw: Any,
              before_aliases: frozenset[str] = frozenset()) -> Dict[str, Dict[str, Any]]:
    """Deterministically validate verifier output. Every task gets a result; DONE/MISSING
    without at least one real supporting observation from an after photo is downgraded to CANT_TELL."""
    items = raw.get("tasks") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ModelError(ErrorCode.MALFORMED_MODEL_OUTPUT, "Verifier did not return a task list.")
    by_task = {}
    for item in items:
        if isinstance(item, dict) and item.get("task_id") in task_aliases and item["task_id"] not in by_task:
            by_task[item["task_id"]] = item

    results = {}
    for alias in task_aliases:
        item = by_task.get(alias)
        if item is None:
            results[alias] = {"status": "CANT_TELL", "reasoning": "The verifier did not assess this requirement.",
                              "observation_aliases": [], "follow_up_request": DEFAULT_FOLLOW_UP, "downgraded": True}
            continue
        status = str(item.get("status") or "").upper()
        reasoning = humanize_refs(str(item.get("reasoning") or ""))[:1000]
        observations = [o for o in (item.get("observation_ids") or []) if isinstance(o, str) and o in obs_aliases]
        downgraded = False
        if status not in STATUSES:
            status, downgraded = "CANT_TELL", True
        if status in ("DONE", "MISSING") and not observations:
            status, downgraded = "CANT_TELL", True
            reasoning = (reasoning + " " if reasoning else "") + "(No supporting observation was cited, so this cannot be confirmed.)"
        elif status in ("DONE", "MISSING") and all(o in before_aliases for o in observations):
            status, downgraded = "CANT_TELL", True
            reasoning = (reasoning + " " if reasoning else "") + "(Only the before photos were cited, so this cannot be confirmed.)"
        follow_up = humanize_refs(str(item.get("follow_up_request") or ""))[:500]
        if status == "CANT_TELL" and not follow_up:
            follow_up = DEFAULT_FOLLOW_UP
        if status != "CANT_TELL":
            follow_up = ""
        results[alias] = {"status": status, "reasoning": reasoning or "No reasoning provided.",
                          "observation_aliases": observations, "follow_up_request": follow_up, "downgraded": downgraded}
    return results


class Verifier:
    async def verify(self, tasks: List[Dict[str, str]], observations: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """tasks: [{"alias", "description", "observable_criteria"}];
        observations: [{"alias", "image_alias", "text", "limitations", "task_aliases"}]"""
        task_listing = "\n".join(f"{t['alias']}: {t['description']} (done when: {t['observable_criteria']})" for t in tasks)
        obs_listing = "\n".join(
            json.dumps({"id": o["alias"], "photo": o["image_alias"], "taken": o.get("taken", "after"), "about": o["task_aliases"],
                        "seen": o["text"], "limitations": o["limitations"]})
            for o in observations
        ) or "(no observations: no usable visual evidence)"
        raw = await meta_client.chat_json(PROMPT % (task_listing, obs_listing))
        return reconcile([t["alias"] for t in tasks], {o["alias"] for o in observations}, raw, before_aliases(observations))


def before_aliases(observations: List[Dict[str, Any]]) -> frozenset[str]:
    return frozenset(o["alias"] for o in observations if o.get("taken") == "before")


verifier = Verifier()
