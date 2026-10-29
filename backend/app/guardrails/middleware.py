from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from .errors import GuardrailValidationError, GuardrailViolation


async def guardrail_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, GuardrailViolation):
        detail = exc.detail.to_dict()
        status_code = 422
        # map specific codes to statuses
        code = detail.get("code", "")
        if code == "FILE_TOO_LARGE" or code == "TOTAL_UPLOAD_TOO_LARGE":
            status_code = 413
        elif code == "UNSUPPORTED_MEDIA_TYPE":
            status_code = 415
        elif code in ("EMPTY_WORK_ORDER", "NO_FILES_UPLOADED"):
            status_code = 400
        elif code in ("VALIDATION_SERVICE_FAILURE", "MODEL_TIMEOUT", "MODEL_RATE_LIMIT", "MODEL_AUTH_FAILURE", "MALFORMED_MODEL_OUTPUT"):
            status_code = 503
        return JSONResponse(status_code=status_code, content={"error": detail})
    if isinstance(exc, GuardrailValidationError):
        # "error" keeps the single-error contract; "errors" lists every problem (e.g. one per bad file).
        details = [d.to_dict() for d in exc.details]
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": details[0] if details else {"message": str(exc)}, "errors": details},
        )
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "stage": "inspection", "message": "Internal server error", "retryable": False}},
    )
