from __future__ import annotations

import os
import uuid
from typing import List

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select

from ..device import current_device
from ..guardrails.errors import (
    ErrorCode, ErrorStage, GuardrailValidationError, GuardrailViolation, ValidationErrorDetail,
)
from ..guardrails.preflight import SemanticPreflight
from ..guardrails.validators import PhotoValidator, RequestValidator, WorkOrderValidator
from ..services.agent.orchestrator import orchestrator
from ..services.persistence import async_session, init_db
from app.models.inspection_models import (
    EvidenceLink, FollowUpRequest, Inspection, InspectionImage, Notification, Observation, Task,
)

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

EXT_BY_FORMAT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MAX_FOLLOW_UP_FILES = 5


@router.on_event("startup")
async def startup():
    await init_db()


async def preflight_work_order(work_order_text: str) -> None:
    preflight =await SemanticPreflight.preflight_work_order(work_order_text)
    if preflight.classification in ("REJECT", "CLARIFY"):
        rejected = preflight.classification == "REJECT"
        raise GuardrailViolation(
            ValidationErrorDetail(
                code=ErrorCode.WORK_ORDER_OUT_OF_SCOPE if rejected else ErrorCode.WORK_ORDER_AMBIGUOUS,
                stage=ErrorStage.WORK_ORDER_VALIDATION,
                message=preflight.reason or ("Work order is out of scope." if rejected else "Work order needs clarification."),
                suggestion=preflight.suggestion or "List specific, observable tasks (e.g. 'Install two outlet covers').",
                retryable=True,
                field="work_order_text",
            )
        )


async def read_and_validate_files(files: List[UploadFile], before_files: List[UploadFile] = ()) -> List[dict]:
    """Validate every file; report every bad file at once rather than stopping at the first.
    Before photos come first in the result and are reported as before_NN, after photos as upload_NN."""
    contents = ([("before", f"before_{i:02d}", f, await f.read()) for i, f in enumerate(before_files, 1)]
                + [(None, f"upload_{i:02d}", f, await f.read()) for i, f in enumerate(files, 1)])
    PhotoValidator.validate_total_size(sum(len(c) for *_, c in contents))
    accepted, problems = [], []
    for role, file_id, upload, content in contents:
        name = upload.filename or file_id
        try:
            PhotoValidator.validate_file_size(name, content, file_id)
            img = PhotoValidator.validate_format_and_decode(name, content, upload.content_type, file_id)
        except GuardrailViolation as e:
            problems.append(e.detail)
            continue
        accepted.append({"file_id": file_id, "role": role, "name": os.path.basename(name), "content": content,
                         "format": img.format, "width": img.width, "height": img.height})
    if problems:
        raise GuardrailValidationError(problems)
    return accepted


async def store_images(session, inspection_id: str, accepted: List[dict]) -> List[InspectionImage]:
    rows = []
    for item in accepted:
        path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}{EXT_BY_FORMAT.get(item['format'], '.img')}")
        async with aiofiles.open(path, "wb") as out:
            await out.write(item["content"])
        row = InspectionImage(inspection_id=inspection_id, filename=item["name"], storage_path=path,
                              mime_type=f"image/{(item['format'] or '').lower()}", size_bytes=len(item["content"]),
                              width=item["width"], height=item["height"], validation_state="VALID", role=item.get("role"))
        session.add(row)
        rows.append(row)
    return rows


@router.post("/inspections", status_code=202)
async def create_inspection(background_tasks: BackgroundTasks, work_order_text: str = Form(""),
                            files: List[UploadFile] = File(default=[]), before_files: List[UploadFile] = File(default=[]),
                            device: str = Depends(current_device)):
    # Cheap deterministic checks first; the model-based scope check runs only on otherwise valid input.
    if before_files and not files:
        raise GuardrailViolation(ValidationErrorDetail(
            code=ErrorCode.NO_FILES_UPLOADED, stage=ErrorStage.REQUEST_VALIDATION,
            message="Before photos were added, but no after photos.",
            suggestion="Add at least one photo of the finished work; before photos are only compared against it.",
            retryable=True, field="files"))
    RequestValidator.validate_request_meta(work_order_text, len(files) + len(before_files))
    WorkOrderValidator.validate_deterministic(work_order_text)
    accepted = await read_and_validate_files(files, before_files)
    await preflight_work_order(work_order_text)

    first_line = next((l.strip(" -*•\t") for l in work_order_text.splitlines() if l.strip()), "Inspection")
    async with async_session() as session:
        insp = Inspection(work_order_text=work_order_text.strip(), status="QUEUED", title=first_line[:80], device_id=device)
        session.add(insp)
        await session.flush()
        await store_images(session, insp.id, accepted)
        await session.commit()
        inspection_id = insp.id

    background_tasks.add_task(orchestrator.run_inspection, inspection_id)
    return {"inspection_id": inspection_id, "status": "QUEUED", "status_url": f"/api/inspections/{inspection_id}"}


@router.post("/inspections/{inspection_id}/retry", status_code=202)
async def retry_inspection(inspection_id: str, background_tasks: BackgroundTasks, device: str = Depends(current_device)):
    """Re-run a FAILED inspection from scratch with the same work order and photos."""
    async with async_session() as session:
        insp = await _get_inspection_or_404(session, inspection_id, device)
        if insp.status != "FAILED":
            raise HTTPException(409, detail={"code": "NOT_RETRYABLE", "retryable": False,
                                             "message": "Only an inspection that failed for a technical reason can be retried."})
        # A failed run can leave partial rows (tasks from planning, observations from analysis); start clean.
        task_ids = [t.id for t in (await session.execute(select(Task).where(Task.inspection_id == inspection_id))).scalars()]
        if task_ids:
            await session.execute(delete(EvidenceLink).where(EvidenceLink.task_id.in_(task_ids)))
        for model in (FollowUpRequest, Observation, Task):
            await session.execute(delete(model).where(model.inspection_id == inspection_id))
        for img in (await session.execute(select(InspectionImage).where(InspectionImage.inspection_id == inspection_id))).scalars():
            img.analysis_state = "PENDING"
        insp.status, insp.error_code, insp.error_message = "QUEUED", None, None
        insp.overall_outcome = insp.summary = insp.agent_trace = None
        await session.commit()

    background_tasks.add_task(orchestrator.run_inspection, inspection_id)
    return {"inspection_id": inspection_id, "status": "QUEUED"}


@router.post("/inspections/{inspection_id}/tasks/{task_id}/follow-up-photos", status_code=202)
async def add_follow_up_photos(inspection_id: str, task_id: str, background_tasks: BackgroundTasks,
                               files: List[UploadFile] = File(default=[]), device: str = Depends(current_device)):
    """Attach photos answering a follow-up request, then re-check that one requirement in the background."""
    if not files or len(files) > MAX_FOLLOW_UP_FILES:
        raise GuardrailViolation(ValidationErrorDetail(
            code=ErrorCode.NO_FILES_UPLOADED if not files else ErrorCode.TOO_MANY_FILES,
            stage=ErrorStage.REQUEST_VALIDATION,
            message="Attach at least one photo." if not files else f"Attach at most {MAX_FOLLOW_UP_FILES} photos per follow-up.",
            suggestion="Take the photo described in the follow-up request.", retryable=True, field="files"))
    async with async_session() as session:
        insp = await _get_inspection_or_404(session, inspection_id, device)
        task = await session.get(Task, task_id)
        if not task or task.inspection_id != inspection_id:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Requirement not found."})
        follow_up = (await session.execute(select(FollowUpRequest).where(FollowUpRequest.task_id == task_id))).scalars().first()
        if insp.status not in ("NEEDS_USER_ACTION", "COMPLETED") or not follow_up or follow_up.status != "PENDING":
            raise HTTPException(409, detail={
                "code": "FOLLOW_UP_NOT_OPEN",
                "message": "This requirement is not waiting for a photo." if insp.status in ("NEEDS_USER_ACTION", "COMPLETED")
                else "The inspection is busy. Wait for the current check to finish.",
                "retryable": True})

    accepted = await read_and_validate_files(files)
    async with async_session() as session:
        rows = await store_images(session, inspection_id, accepted)
        follow_up = await session.get(FollowUpRequest, follow_up.id)
        follow_up.status, follow_up.last_error = "CHECKING", None
        await session.flush()
        follow_up.linked_follow_up_image_ids = list(follow_up.linked_follow_up_image_ids or []) + [r.id for r in rows]
        (await session.get(Inspection, inspection_id)).status = "REVERIFYING"
        await session.commit()
        image_ids = [r.id for r in rows]

    background_tasks.add_task(orchestrator.recheck_task, inspection_id, task_id, image_ids)
    return {"inspection_id": inspection_id, "task_id": task_id, "status": "REVERIFYING", "image_ids": image_ids}


async def _get_inspection_or_404(session, inspection_id: str, device: str) -> Inspection:
    insp = await session.get(Inspection, inspection_id)
    if not insp or insp.device_id != device:  # another device's inspection looks the same as a missing one
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Inspection not found."})
    return insp


def _counts(tasks) -> dict:
    statuses = [t.status for t in tasks]
    return {s.lower(): statuses.count(s) for s in ("DONE", "MISSING", "CANT_TELL")}


@router.get("/inspections")
async def list_inspections(limit: int = 50, device: str = Depends(current_device)):
    async with async_session() as session:
        rows = (await session.execute(
            select(Inspection).where(Inspection.device_id == device).order_by(Inspection.created_at.desc()).limit(min(limit, 200))
        )).scalars().all()
        out = []
        for insp in rows:
            tasks = (await session.execute(select(Task).where(Task.inspection_id == insp.id))).scalars().all()
            out.append({
                "inspection_id": insp.id, "title": insp.title, "status": insp.status,
                "overall_outcome": insp.overall_outcome, "created_at": insp.created_at.isoformat() + "Z",
                "counts": _counts(tasks), "needs_action": insp.status in ("NEEDS_USER_ACTION", "FAILED"),
            })
        return {"inspections": out}


@router.get("/inspections/{inspection_id}")
async def get_inspection(inspection_id: str, device: str = Depends(current_device)):
    async with async_session() as session:
        insp = await _get_inspection_or_404(session, inspection_id, device)
        tasks = (await session.execute(select(Task).where(Task.inspection_id == inspection_id))).scalars().all()
        image_count = (await session.execute(
            select(func.count()).select_from(InspectionImage).where(InspectionImage.inspection_id == inspection_id)
        )).scalar_one()
        return {
            "inspection_id": insp.id,
            "title": insp.title,
            "status": insp.status,
            "overall_outcome": insp.overall_outcome,
            "summary": insp.summary,
            "error": {"code": insp.error_code, "message": insp.error_message} if insp.error_code else None,
            "tasks_count": len(tasks),
            "images_count": image_count,
            "counts": _counts(tasks),
            "created_at": insp.created_at.isoformat() + "Z",
            "updated_at": insp.updated_at.isoformat() + "Z",
        }


@router.get("/inspections/{inspection_id}/report")
async def get_report(inspection_id: str, device: str = Depends(current_device)):
    async with async_session() as session:
        insp = await _get_inspection_or_404(session, inspection_id, device)
        tasks = (await session.execute(
            select(Task).where(Task.inspection_id == inspection_id).order_by(Task.created_at)
        )).scalars().all()
        images = (await session.execute(
            select(InspectionImage).where(InspectionImage.inspection_id == inspection_id).order_by(InspectionImage.created_at)
        )).scalars().all()
        observations = (await session.execute(
            select(Observation).where(Observation.inspection_id == inspection_id).order_by(Observation.created_at)
        )).scalars().all()
        task_ids = [t.id for t in tasks]
        links = (await session.execute(select(EvidenceLink).where(EvidenceLink.task_id.in_(task_ids)))).scalars().all() if task_ids else []
        follow_ups = (await session.execute(
            select(FollowUpRequest).where(FollowUpRequest.inspection_id == inspection_id)
        )).scalars().all()

        steps_by_task: dict = {}
        for step in insp.agent_trace or []:
            steps_by_task.setdefault(step.get("task_id"), []).append(
                {k: step.get(k) for k in ("tool", "args", "ok", "result", "ms", "round")})

        links_by_task: dict = {}
        for link in links:
            links_by_task.setdefault(link.task_id, []).append(link)
        follow_up_by_task = {f.task_id: f for f in follow_ups}
        follow_up_image = {img_id: f.task_id for f in follow_ups for img_id in (f.linked_follow_up_image_ids or [])}

        return {
            "inspection_id": insp.id,
            "title": insp.title,
            "work_order_text": insp.work_order_text,
            "status": insp.status,
            "overall_outcome": insp.overall_outcome,
            "summary": insp.summary,
            "error": {"code": insp.error_code, "message": insp.error_message} if insp.error_code else None,
            "counts": _counts(tasks),
            "created_at": insp.created_at.isoformat() + "Z",
            "images": [{
                "id": i.id, "filename": i.filename, "width": i.width, "height": i.height,
                "analysis_state": i.analysis_state, "follow_up_for": follow_up_image.get(i.id), "role": i.role or "after",
                "url": f"/api/inspections/{inspection_id}/images/{i.id}",
            } for i in images],
            "observations": [{
                "id": o.id, "image_id": o.image_id, "task_ids": o.relevant_task_ids or [],
                "source": (o.meta_data or {}).get("source"), "compared_with": (o.meta_data or {}).get("before_image_id"),
                "text": o.observation_text, "limitations": o.limitations,
            } for o in observations],
            "tasks": [{
                "id": t.id,
                "description": t.description,
                "observable_criteria": t.observable_criteria,
                "status": t.status,
                "reasoning": t.reasoning,
                "observation_ids": [l.observation_id for l in links_by_task.get(t.id, [])],
                "evidence": [{"image_id": l.image_id, "observation_id": l.observation_id,
                              "regions": l.region, "region_source": l.region_source}
                             for l in links_by_task.get(t.id, [])],
                "follow_up": ({"id": follow_up_by_task[t.id].id, "needed": follow_up_by_task[t.id].status in ("PENDING", "CHECKING"),
                               "request": follow_up_by_task[t.id].request_text, "status": follow_up_by_task[t.id].status,
                               "last_error": follow_up_by_task[t.id].last_error,
                               "image_ids": follow_up_by_task[t.id].linked_follow_up_image_ids or []}
                              if t.id in follow_up_by_task else None),
                "investigation": steps_by_task.get(t.id, []),
            } for t in tasks],
        }


@router.get("/inspections/{inspection_id}/images/{image_id}")
async def get_image(inspection_id: str, image_id: str, device: str = Depends(current_device)):
    async with async_session() as session:
        await _get_inspection_or_404(session, inspection_id, device)
        img = await session.get(InspectionImage, image_id)
        if not img or img.inspection_id != inspection_id or not os.path.isfile(img.storage_path):
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Image not found."})
        return FileResponse(img.storage_path, media_type=img.mime_type or "application/octet-stream")
