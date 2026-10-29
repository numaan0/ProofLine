import asyncio

import pytest
from fastapi.testclient import TestClient

from app.device import DEVICE_COOKIE
from app.main import app
from app.models.inspection_models import Inspection, Notification
from tests.conftest import TEST_DEVICE


@pytest.fixture
def client(temp_db):
    async def seed():
        async with temp_db() as s:
            insp = Inspection(work_order_text="Install covers", title="Install covers", status="COMPLETED", device_id=TEST_DEVICE)
            s.add(insp)
            await s.flush()
            s.add_all([Notification(inspection_id=insp.id, type="INSPECTION_COMPLETED", title="Report ready", message="m"),
                       Notification(inspection_id=insp.id, type="FOLLOW_UP_REQUESTED", title="More photos", message="m")])
            await s.commit()

    asyncio.run(seed())
    with TestClient(app, cookies={DEVICE_COOKIE: TEST_DEVICE}) as c:
        yield c


def test_list_and_mark_read(client):
    body = client.get("/api/notifications").json()
    assert body["unread_count"] == 2
    first = body["notifications"][0]
    assert first["inspection_title"] == "Install covers" and first["read"] is False

    assert client.post(f"/api/notifications/{first['id']}/read").json()["read"] is True
    body = client.get("/api/notifications").json()
    assert body["unread_count"] == 1
    assert len(client.get("/api/notifications?unread_only=true").json()["notifications"]) == 1

    assert client.post("/api/notifications/read-all").json()["unread_count"] == 0
    assert client.get("/api/notifications").json()["unread_count"] == 0


def test_unknown_notification_404(client):
    assert client.post("/api/notifications/notif_nope/read").status_code == 404


def test_other_device_sees_no_notifications(client):
    with TestClient(app) as other:
        body = other.get("/api/notifications").json()
        assert body == {"unread_count": 0, "notifications": []}
        assert other.post("/api/notifications/read-all").status_code == 200
    first = client.get("/api/notifications").json()
    assert first["unread_count"] == 2, "another device's read-all must not touch these"
    with TestClient(app) as other:
        assert other.post(f"/api/notifications/{first['notifications'][0]['id']}/read").status_code == 404
