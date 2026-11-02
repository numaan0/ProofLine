"""Email summaries: composed after every run, sent over SMTP when configured, otherwise kept in the outbox."""
import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.services.agent.orchestrator as orch_mod
import app.services.email_summary as email_mod
from app.main import app
from app.models.inspection_models import EmailSummary, Inspection
from app.services.meta_client import meta_client
from tests.test_inspections_api import client, png_bytes  # noqa: F401  (fixture reuse)
from tests.test_orchestrator import PLAN, make_inspection, scripted_chat_json

ANALYSES = [{"image_class": "USABLE", "observations": [
    {"text": "Right outlet has no cover plate", "task_ids": ["T1"], "object_phrase": ""}]},
    {"image_class": "IRRELEVANT", "observations": []}]
VERDICT = {"tasks": [
    {"task_id": "T1", "status": "MISSING", "reasoning": "One outlet has no plate.", "observation_ids": ["O1"]},
    {"task_id": "T2", "status": "CANT_TELL", "reasoning": "Wall not shown.", "observation_ids": [],
     "follow_up_request": "Photograph the full repainted wall."}]}


def run_with_recipient(temp_db, tmp_path, monkeypatch, recipient):
    insp_id = make_inspection(temp_db, tmp_path)

    async def set_recipient():
        async with temp_db() as s:
            (await s.get(Inspection, insp_id)).notify_email = recipient
            await s.commit()

    asyncio.run(set_recipient())
    monkeypatch.setattr(meta_client, "chat_json", scripted_chat_json(PLAN, ANALYSES, VERDICT))
    asyncio.run(orch_mod.orchestrator.run_inspection(insp_id))

    async def emails():
        async with temp_db() as s:
            return (await s.execute(select(EmailSummary))).scalars().all()

    return insp_id, asyncio.run(emails())


def test_summary_kept_in_outbox_without_smtp(temp_db, tmp_path, monkeypatch):
    insp_id, emails = run_with_recipient(temp_db, tmp_path, monkeypatch, "manager@example.com")
    assert len(emails) == 1
    m = emails[0]
    assert m.status == "OUTBOX" and "SMTP is not configured" in m.detail and m.to_address == "manager@example.com"
    assert m.subject.endswith("— 1 not met")
    body = m.body_text
    assert body.index("NOT MET") < body.index("NEEDS EVIDENCE"), "problems are listed first"
    assert "Photo needed: Photograph the full repainted wall." in body
    assert f"/#/inspections/{insp_id}" in body
    assert (tmp_path / "outbox" / f"{m.id}.eml").exists()


def test_summary_sent_over_smtp_when_configured(temp_db, tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(email_mod, "_config", lambda: {"SMTP_HOST": "smtp.test", "SMTP_PORT": "587", "SMTP_USER": "",
                                                       "SMTP_PASSWORD": "", "SMTP_FROM": "", "APP_URL": ""})
    monkeypatch.setattr(email_mod, "_smtp_send", lambda cfg, msg: sent.append(msg))
    _, emails = run_with_recipient(temp_db, tmp_path, monkeypatch, "manager@example.com")
    assert emails[0].status == "SENT" and sent and sent[0]["To"] == "manager@example.com"
    assert not (tmp_path / "outbox").exists(), "a sent email is not also kept in the outbox"


def test_smtp_failure_never_affects_the_inspection(temp_db, tmp_path, monkeypatch):
    def boom(cfg, msg):
        raise ConnectionRefusedError()

    monkeypatch.setattr(email_mod, "_config", lambda: {"SMTP_HOST": "smtp.test", "SMTP_PORT": "587", "SMTP_USER": "",
                                                       "SMTP_PASSWORD": "", "SMTP_FROM": "", "APP_URL": ""})
    monkeypatch.setattr(email_mod, "_smtp_send", boom)
    insp_id, emails = run_with_recipient(temp_db, tmp_path, monkeypatch, "manager@example.com")
    assert emails[0].status == "FAILED" and "ConnectionRefusedError" in emails[0].detail

    async def status():
        async with temp_db() as s:
            return (await s.get(Inspection, insp_id)).status

    assert asyncio.run(status()) == "NEEDS_USER_ACTION"


def test_no_recipient_still_writes_a_preview(temp_db, tmp_path, monkeypatch):
    _, emails = run_with_recipient(temp_db, tmp_path, monkeypatch, None)
    assert emails[0].status == "OUTBOX" and "No email address" in emails[0].detail


def test_api_validates_and_scopes_email(client):  # noqa: F811
    bad = client.post("/api/inspections", data={"work_order_text": "Install two outlet covers", "notify_email": "not-an-email"},
                      files=[("files", ("a.png", png_bytes(), "image/png"))])
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_EMAIL"

    r = client.post("/api/inspections", data={"work_order_text": "Install two outlet covers", "notify_email": " manager@example.com "},
                    files=[("files", ("a.png", png_bytes(), "image/png"))])
    insp_id = r.json()["inspection_id"]
    assert asyncio.run(email_mod.send_summary(insp_id))
    report = client.get(f"/api/inspections/{insp_id}/report").json()
    assert report["emails"][0]["to"] == "manager@example.com" and report["emails"][0]["status"] == "OUTBOX"
    email_url = f"/api/inspections/{insp_id}/emails/{report['emails'][0]['id']}"
    assert "Open the report" in client.get(email_url).json()["body"]
    with TestClient(app) as other:
        assert other.get(email_url).status_code == 404
