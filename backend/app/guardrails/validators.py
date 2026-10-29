from __future__ import annotations

import io
import os
from typing import Optional, Tuple

from PIL import Image

from .config import config
from .errors import ErrorCode, ErrorStage, GuardrailViolation, ValidationErrorDetail


SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
SUPPORTED_MIMES = {"image/jpeg", "image/png", "image/webp"}


class RequestValidator:
    @staticmethod
    def validate_request_meta(work_order_text: str, file_count: int) -> None:
        if file_count == 0:
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.NO_FILES_UPLOADED,
                    stage=ErrorStage.REQUEST_VALIDATION,
                    message="At least one site photo is required for inspection.",
                    suggestion="Upload photos showing the work to be verified.",
                    retryable=True,
                    field="files",
                )
            )
        if file_count > config.max_files:
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.TOO_MANY_FILES,
                    stage=ErrorStage.REQUEST_VALIDATION,
                    message=f"Too many files uploaded. Maximum is {config.max_files}.",
                    suggestion="Upload fewer photos and focus on the areas relevant to the work order.",
                    retryable=True,
                    field="files",
                )
            )


class WorkOrderValidator:
    INJECTION_PATTERNS = [
        "ignore previous",
        "ignore all previous",
        "system prompt",
        "you are now",
        "act as",
        "jailbreak",
        "override",
        "tool_call",
        "function call",
    ]
    SCOPE_KEYWORDS = [
        "install", "replace", "repair", "paint", "seal", "caulk", "tile", "floor", "wall",
        "ceiling", "door", "window", "outlet", "switch", "plumb", "fixture", "cabinet",
        "trim", "grout", "patch", "cover", "mount", "attach", "finish", "inspect", "check",
        "verify", "complete", "done", "work", "job", "task",
    ]
    OUT_OF_SCOPE = ["weather", "poem", "recipe", "joke", "story", "news", "stock"]

    @classmethod
    def validate_deterministic(cls, work_order_text: str) -> None:
        if not work_order_text or not work_order_text.strip():
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.EMPTY_WORK_ORDER,
                    stage=ErrorStage.WORK_ORDER_VALIDATION,
                    message="Work order text is required.",
                    suggestion="Add one task per line describing physical work to verify.",
                    retryable=True,
                    field="work_order_text",
                )
            )
        text = work_order_text.strip()
        if len(text) < config.min_work_order_chars:
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.WORK_ORDER_TOO_SHORT,
                    stage=ErrorStage.WORK_ORDER_VALIDATION,
                    message="Work order is too short to be actionable.",
                    suggestion="Describe specific tasks (e.g., 'Install 2 electrical outlet covers').",
                    retryable=True,
                    field="work_order_text",
                )
            )
        if len(text) > config.max_work_order_chars:
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.WORK_ORDER_TOO_LONG,
                    stage=ErrorStage.WORK_ORDER_VALIDATION,
                    message=f"Work order exceeds {config.max_work_order_chars} characters.",
                    suggestion="Break into a concise list of verifiable tasks.",
                    retryable=True,
                    field="work_order_text",
                )
            )
        lower = text.lower()
        for pattern in cls.INJECTION_PATTERNS:
            if pattern in lower:
                raise GuardrailViolation(
                    ValidationErrorDetail(
                        code=ErrorCode.WORK_ORDER_INJECTION_ATTEMPT,
                        stage=ErrorStage.WORK_ORDER_VALIDATION,
                        message="The work order contains instructions that cannot be processed.",
                        suggestion="Describe physical tasks only (e.g., install, paint, seal).",
                        retryable=True,
                        field="work_order_text",
                    )
                )
        # Check obvious out of scope
        if any(k in lower for k in cls.OUT_OF_SCOPE) and not any(k in lower for k in cls.SCOPE_KEYWORDS):
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.WORK_ORDER_OUT_OF_SCOPE,
                    stage=ErrorStage.WORK_ORDER_VALIDATION,
                    message="This request is outside the scope of photo-based work verification.",
                    suggestion="Describe physical work or conditions that can be assessed from photos.",
                    retryable=True,
                    field="work_order_text",
                )
            )
        # Check if too ambiguous
        lines = [l.strip() for l in text.split('\n') if l.strip() and not l.strip().startswith('#')]
        if lines:
            vague = ["fix everything", "check the place", "make it look good", "do it all"]
            if any(v in lower for v in vague):
                raise GuardrailViolation(
                    ValidationErrorDetail(
                        code=ErrorCode.WORK_ORDER_AMBIGUOUS,
                        stage=ErrorStage.WORK_ORDER_VALIDATION,
                        message="The work order is too ambiguous to verify from photos.",
                        suggestion="List specific, observable items (e.g., 'Seal bathroom perimeter with caulk').",
                        retryable=True,
                        field="work_order_text",
                    )
                )


class PhotoValidator:
    @staticmethod
    def validate_file_size(filename: str, content: bytes, file_id: str) -> None:
        if len(content) > config.max_file_bytes:
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.FILE_TOO_LARGE,
                    stage=ErrorStage.PHOTO_VALIDATION,
                    message=f"{filename} exceeds the {config.max_file_bytes // (1024*1024)}MB limit.",
                    suggestion="Compress the image or upload a smaller version.",
                    retryable=True,
                    field="files",
                    file_id=file_id,
                )
            )

    @staticmethod
    def validate_total_size(total_bytes: int) -> None:
        if total_bytes > config.max_total_bytes:
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.TOTAL_UPLOAD_TOO_LARGE,
                    stage=ErrorStage.REQUEST_VALIDATION,
                    message=f"Total upload exceeds the {config.max_total_bytes // (1024*1024)}MB limit.",
                    suggestion="Upload fewer or smaller photos.",
                    retryable=True,
                    field="files",
                )
            )

    @staticmethod
    def validate_format_and_decode(filename: str, content: bytes, content_type: Optional[str], file_id: str) -> Image.Image:
        ext = os.path.splitext(filename or "")[1].lower()
        if ext not in SUPPORTED_EXTS:
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                    stage=ErrorStage.PHOTO_VALIDATION,
                    message=f"{filename} has an unsupported format.",
                    suggestion="Upload JPG, PNG, or WebP images.",
                    retryable=True,
                    field="files",
                    file_id=file_id,
                )
            )
        if content_type and content_type not in SUPPORTED_MIMES and content_type != "application/octet-stream":
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                    stage=ErrorStage.PHOTO_VALIDATION,
                    message=f"{filename} has an unsupported media type.",
                    suggestion="Upload JPG, PNG, or WebP images.",
                    retryable=True,
                    field="files",
                    file_id=file_id,
                )
            )
        try:
            Image.open(io.BytesIO(content)).verify()
        except Exception:
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.CORRUPT_IMAGE,
                    stage=ErrorStage.PHOTO_VALIDATION,
                    message=f"{filename} is corrupted or unreadable.",
                    suggestion="Re-export or re-take the photo and try again.",
                    retryable=True,
                    field="files",
                    file_id=file_id,
                )
            )
        try:
            img = Image.open(io.BytesIO(content))
            img.load()
        except Exception:
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.IMAGE_UNREADABLE,
                    stage=ErrorStage.PHOTO_VALIDATION,
                    message=f"{filename} cannot be decoded.",
                    suggestion="Try a different format or re-export the image.",
                    retryable=True,
                    field="files",
                    file_id=file_id,
                )
            )
        w, h = img.size
        if w < config.min_image_width or h < config.min_image_height:
            raise GuardrailViolation(
                ValidationErrorDetail(
                    code=ErrorCode.IMAGE_TOO_SMALL,
                    stage=ErrorStage.PHOTO_VALIDATION,
                    message=f"{filename} is too small for reliable inspection.",
                    suggestion="Upload a higher resolution photo showing more detail.",
                    retryable=True,
                    field="files",
                    file_id=file_id,
                )
            )
        return img
