from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import List
import os
import uuid
import aiofiles
from ..services.inspector import inspector
from ..guardrails.validators import RequestValidator, WorkOrderValidator, PhotoValidator
from ..guardrails.preflight import SemanticPreflight
from ..guardrails.config import config
from ..guardrails.errors import GuardrailViolation, ErrorCode, ErrorStage, ValidationErrorDetail, GuardrailValidationError

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/inspect")
async def inspect(work_order_text: str = Form(...), files: List[UploadFile] = File(...)):
    # Layer A: request meta
    RequestValidator.validate_request_meta(work_order_text, len(files) if files else 0)

    # Layer: work order deterministic
    WorkOrderValidator.validate_deterministic(work_order_text)

    # Layer: semantic preflight for work order
    preflight = await SemanticPreflight.preflight_work_order(work_order_text)
    if preflight.classification == "REJECT":
        raise GuardrailViolation(
            ValidationErrorDetail(
                code=ErrorCode.WORK_ORDER_OUT_OF_SCOPE,
                stage=ErrorStage.WORK_ORDER_VALIDATION,
                message=preflight.reason or "Work order rejected by validation.",
                suggestion=preflight.suggestion or "Describe physical work verifiable from photos.",
                retryable=True,
                field="work_order_text",
            )
        )
    if preflight.classification == "CLARIFY":
        raise GuardrailViolation(
            ValidationErrorDetail(
                code=ErrorCode.WORK_ORDER_AMBIGUOUS,
                stage=ErrorStage.WORK_ORDER_VALIDATION,
                message=preflight.reason or "Work order needs clarification.",
                suggestion=preflight.suggestion or "List specific, observable tasks.",
                retryable=True,
                field="work_order_text",
            )
        )

    # Read and validate files
    saved_paths = []
    eligible_paths = []
    file_metadata = []
    total_bytes = 0
    read_contents = []

    for idx, file in enumerate(files):
        file_id = f"file_{idx + 1}"
        content = await file.read()
        read_contents.append((file, content, file_id))
        total_bytes += len(content)

    PhotoValidator.validate_total_size(total_bytes)

    for file, content, file_id in read_contents:
        PhotoValidator.validate_file_size(file.filename or f"upload{idx+1}", content, file_id)
        img = PhotoValidator.validate_format_and_decode(file.filename or "", content, file.content_type, file_id)
        ext = os.path.splitext(file.filename or "")[1].lower() or '.jpg'
        filename = f"{uuid.uuid4()}{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        async with aiofiles.open(filepath, 'wb') as out_file:
            await out_file.write(content)
        saved_paths.append(filepath)
        eligible_paths.append(filepath)
        file_metadata.append({"path": filepath, "name": file.filename, "id": file_id})

    if not eligible_paths:
        raise GuardrailViolation(
            ValidationErrorDetail(
                code=ErrorCode.ALL_IMAGES_UNUSABLE,
                stage=ErrorStage.PHOTO_VALIDATION,
                message="No usable images remain after validation.",
                suggestion="Upload clear, readable photos of the work area.",
                retryable=True,
                field="files",
            )
        )

    # Semantic photo preflight for eligible images (best effort)
    bad_photos = []
    for meta in file_metadata:
        try:
            pf = await SemanticPreflight.preflight_photo(meta["path"], work_order_text)
            if pf.classification in ("IRRELEVANT", "NOT_A_PHOTO"):
                bad_photos.append(meta)
            # LOW_QUALITY/INCONCLUSIVE - don't block, just note
        except Exception:
            continue

    if bad_photos and len(bad_photos) == len(eligible_paths):
        raise GuardrailViolation(
            ValidationErrorDetail(
                code=ErrorCode.ALL_IMAGES_UNUSABLE,
                stage=ErrorStage.PHOTO_VALIDATION,
                message="All submitted photos appear unusable for this inspection.",
                suggestion="Upload photos that show the areas relevant to the listed tasks.",
                retryable=True,
                field="files",
            )
        )
    # If some bad, we still proceed with eligible (we kept all valid decoded ones) - could filter, but keep behavior safe
    result = await inspector.inspect(work_order_text, eligible_paths)
    return result