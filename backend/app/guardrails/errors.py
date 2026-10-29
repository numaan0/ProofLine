from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class ErrorCode(str, Enum):
    EMPTY_WORK_ORDER = "EMPTY_WORK_ORDER"
    WORK_ORDER_TOO_LONG = "WORK_ORDER_TOO_LONG"
    WORK_ORDER_TOO_SHORT = "WORK_ORDER_TOO_SHORT"
    WORK_ORDER_OUT_OF_SCOPE = "WORK_ORDER_OUT_OF_SCOPE"
    WORK_ORDER_AMBIGUOUS = "WORK_ORDER_AMBIGUOUS"
    WORK_ORDER_INJECTION_ATTEMPT = "WORK_ORDER_INJECTION_ATTEMPT"
    NO_FILES_UPLOADED = "NO_FILES_UPLOADED"
    TOO_MANY_FILES = "TOO_MANY_FILES"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    TOTAL_UPLOAD_TOO_LARGE = "TOTAL_UPLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    CORRUPT_IMAGE = "CORRUPT_IMAGE"
    IMAGE_TOO_SMALL = "IMAGE_TOO_SMALL"
    IMAGE_UNREADABLE = "IMAGE_UNREADABLE"
    ALL_IMAGES_UNUSABLE = "ALL_IMAGES_UNUSABLE"
    PHOTO_UNUSABLE = "PHOTO_UNUSABLE"
    PHOTO_IRRELEVANT = "PHOTO_IRRELEVANT"
    PHOTO_NOT_A_PHOTO = "PHOTO_NOT_A_PHOTO"
    PHOTO_LOW_QUALITY = "PHOTO_LOW_QUALITY"
    PRECHECK_INCONCLUSIVE = "PRECHECK_INCONCLUSIVE"
    VALIDATION_SERVICE_FAILURE = "VALIDATION_SERVICE_FAILURE"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_AUTH_FAILURE = "MODEL_AUTH_FAILURE"
    MODEL_RATE_LIMIT = "MODEL_RATE_LIMIT"
    MALFORMED_MODEL_OUTPUT = "MALFORMED_MODEL_OUTPUT"
    INVALID_MODEL_REFERENCE = "INVALID_MODEL_REFERENCE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorStage(str, Enum):
    REQUEST_VALIDATION = "request_validation"
    WORK_ORDER_VALIDATION = "work_order_validation"
    PHOTO_VALIDATION = "photo_validation"
    PREFLIGHT = "preflight"
    INSPECTION = "inspection"
    OUTPUT_VALIDATION = "output_validation"


@dataclass
class ValidationErrorDetail:
    code: ErrorCode
    stage: ErrorStage
    message: str
    suggestion: Optional[str] = None
    retryable: bool = False
    field: Optional[str] = None
    file_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "code": self.code.value,
            "stage": self.stage.value,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.suggestion is not None:
            result["suggestion"] = self.suggestion
        if self.field is not None:
            result["field"] = self.field
        if self.file_id is not None:
            result["file_id"] = self.file_id
        return result


class GuardrailViolation(Exception):
    def __init__(self, detail: ValidationErrorDetail):
        self.detail = detail
        super().__init__(detail.message)


def model_error_detail(exc: Exception, stage: "ErrorStage") -> ValidationErrorDetail:
    """Map a services.meta_client.ModelError to the public error contract."""
    messages = {
        ErrorCode.MODEL_TIMEOUT: ("The AI service took too long to respond.", "Try again in a moment."),
        ErrorCode.MODEL_AUTH_FAILURE: ("The AI service is not configured correctly.", "Check the backend API key."),
        ErrorCode.MODEL_RATE_LIMIT: ("The AI service is busy.", "Wait a minute and try again."),
        ErrorCode.MALFORMED_MODEL_OUTPUT: ("The AI service returned an unusable answer.", "Try again."),
    }
    code = getattr(exc, "code", ErrorCode.INTERNAL_ERROR)
    message, suggestion = messages.get(code, ("The AI service is unavailable.", "Try again in a moment."))
    return ValidationErrorDetail(code=code, stage=stage, message=message, suggestion=suggestion,
                                 retryable=getattr(exc, "retryable", True))


class GuardrailValidationError(Exception):
    def __init__(self, details: list[ValidationErrorDetail], status_code: int = 422):
        self.details = details
        self.status_code = status_code
        super().__init__(details[0].message if details else "Validation failed")
