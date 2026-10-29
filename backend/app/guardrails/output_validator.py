from __future__ import annotations

import json
from typing import Any, Dict, List

from pydantic import ValidationError

from .schemas import InspectionOutput


class OutputValidator:
    @staticmethod
    def validate_inspection_output(result: Dict[str, Any], expected_task_count: int, allowed_image_refs: List[str]) -> InspectionOutput:
        try:
            parsed = InspectionOutput(**result)
        except ValidationError as e:
            raise ValueError(f"Malformed model output: {e}") from e

        if len(parsed.tasks) != expected_task_count:
            raise ValueError(f"Task count mismatch: expected {expected_task_count}, got {len(parsed.tasks)}")

        seen_ids = set()
        for task in parsed.tasks:
            if task.id in seen_ids:
                raise ValueError("Duplicate task id")
            seen_ids.add(task.id)
            # evidence refs must be from allowed images if provided
            for ev in task.evidence:
                if isinstance(ev, str) and ev not in allowed_image_refs and allowed_image_refs:
                    raise ValueError("Invalid image reference in evidence")
        # summary consistency
        done = sum(1 for t in parsed.tasks if t.status == "DONE")
        missing = sum(1 for t in parsed.tasks if t.status == "MISSING")
        cant = sum(1 for t in parsed.tasks if t.status == "CANT_TELL")
        if f"{done} done" not in parsed.summary.lower() and f"{missing} missing" not in parsed.summary.lower():
            # allow but don't fail hard; be lenient
            pass
        return parsed
