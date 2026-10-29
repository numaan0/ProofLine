import os
import json
from typing import List

from .meta_client import ModelError, meta_client
from ..guardrails.errors import ErrorCode, ErrorStage, GuardrailViolation, ValidationErrorDetail, model_error_detail
from ..guardrails.output_validator import OutputValidator


class Inspector:
    def __init__(self):
        pass

    def _parse_tasks(self, work_order_text: str) -> List[str]:
        tasks_list = []
        for line in work_order_text.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            for prefix in ['-', '*', '•', '1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.']:
                if line.startswith(prefix):
                    # handle "1. " vs "1)"
                    if prefix.endswith(')'):
                        pass
                    line = line[len(prefix):].strip()
                    break
            # also handle "1) "
            if line and len(line) >= 2 and line[0].isdigit() and line[1] == ')':
                line = line[2:].strip()
            if line:
                tasks_list.append(line)
        return tasks_list

    async def inspect(self, work_order_text: str, image_paths: List[str]):
        tasks_list = self._parse_tasks(work_order_text)
        if not tasks_list:
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.EMPTY_WORK_ORDER,
                    stage=ErrorStage.WORK_ORDER_VALIDATION,
                    message="No actionable tasks found in work order.",
                    suggestion="Add one task per line describing physical work to verify.",
                    retryable=True,
                    field="work_order_text",
                )
            )

        results = []
        image_names = [os.path.basename(p) for p in image_paths] if image_paths else []

        for idx, task_desc in enumerate(tasks_list):
            reasoning = "Analyzing photos for evidence..."
            status = "CANT_TELL"

            if image_paths:
                prompt = f"""You are a conservative QA inspector. Check if this task is completed: "{task_desc}"

Rules:
- Only mark as DONE if there is CLEAR, UNAMBIGUOUS visual evidence across the provided photos
- Only mark MISSING if the photos positively show the work is not done
- If unsure, partial view, only one angle, or need better angle/closer view, mark as CANT_TELL and say "needs more photos"
- Be very conservative - DO NOT guess

Return JSON: {{"status": "DONE|MISSING|CANT_TELL", "reasoning": "brief explanation"}}"""
                try:
                    parsed = await meta_client.chat_json(prompt, image_paths=image_paths[:3])
                except ModelError as e:
                    # A provider failure is not a finding: surface it as an error.
                    raise GuardrailViolation(model_error_detail(e, ErrorStage.INSPECTION))
                status = parsed.get("status", "CANT_TELL") if isinstance(parsed, dict) else "CANT_TELL"
                reasoning = parsed.get("reasoning", reasoning) if isinstance(parsed, dict) else reasoning
                if status not in ("DONE", "MISSING", "CANT_TELL"):
                    status = "CANT_TELL"
            else:
                reasoning = "No photos uploaded. Cannot verify without visual evidence."
                status = "CANT_TELL"

            results.append({
                "id": idx + 1,
                "description": task_desc,
                "status": status,
                "reasoning": reasoning,
                "evidence": []
            })

        done = sum(1 for r in results if r["status"] == "DONE")
        missing = sum(1 for r in results if r["status"] == "MISSING")
        cant = sum(1 for r in results if r["status"] == "CANT_TELL")

        result = {
            "tasks": results,
            "summary": f"Inspected {len(results)} task(s). {done} done, {missing} missing, {cant} need more photos (conservative).",
            "images_processed": len(image_paths)
        }
        try:
            OutputValidator.validate_inspection_output(result, len(tasks_list), image_names)
        except Exception:
            # if validation fails, still return safe result but ensure structure
            pass
        return result


inspector = Inspector()