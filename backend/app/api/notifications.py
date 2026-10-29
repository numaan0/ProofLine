from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update

from ..device import current_device
from ..services.persistence import async_session
from app.models.inspection_models import Inspection, Notification

router = APIRouter()

# No sign-in: a notification belongs to the device that owns its inspection (app/device.py).


def _serialize(n: Notification, title: str | None) -> dict:
    return {
        "id": n.id,
        "inspection_id": n.inspection_id,
        "inspection_title": title,
        "type": n.type,
        "title": n.title,
        "message": n.message,
        "read": bool(n.read_state),
        "created_at": n.created_at.isoformat() + "Z",
    }


def _device_inspections(device: str):
    return select(Inspection.id).where(Inspection.device_id == device)


@router.get("/notifications")
async def list_notifications(limit: int = 50, unread_only: bool = False, device: str = Depends(current_device)):
    async with async_session() as session:
        query = (select(Notification, Inspection.title)
                 .join(Inspection, Inspection.id == Notification.inspection_id)
                 .where(Inspection.device_id == device)
                 .order_by(Notification.created_at.desc()).limit(min(limit, 200)))
        if unread_only:
            query = query.where(Notification.read_state.is_(False))
        rows = (await session.execute(query)).all()
        unread = (await session.execute(
            select(func.count()).select_from(Notification).where(
                Notification.read_state.is_(False), Notification.inspection_id.in_(_device_inspections(device)))
        )).scalar_one()
        return {"unread_count": unread, "notifications": [_serialize(n, title) for n, title in rows]}


@router.post("/notifications/read-all")
async def mark_all_read(device: str = Depends(current_device)):
    async with async_session() as session:
        await session.execute(update(Notification).where(
            Notification.read_state.is_(False), Notification.inspection_id.in_(_device_inspections(device))
        ).values(read_state=True))
        await session.commit()
    return {"unread_count": 0}


@router.post("/notifications/{notification_id}/read")
async def mark_read(notification_id: str, device: str = Depends(current_device)):
    async with async_session() as session:
        n = await session.get(Notification, notification_id)
        insp = n and n.inspection_id and await session.get(Inspection, n.inspection_id)
        if not insp or insp.device_id != device:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Notification not found."})
        n.read_state = True
        await session.commit()
        return {"id": n.id, "read": True}
