"""Email summary of an inspection, written each time a run or a follow-up re-check finishes.

Delivered over SMTP when SMTP_HOST is set and the inspection has a recipient; otherwise the message
is kept in the local outbox (data/outbox/<id>.eml) and the report shows it as a preview. Email is
never required: a failure here is recorded on the message and never changes the inspection.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, Optional

from dotenv import dotenv_values
from sqlalchemy import select

from .persistence import async_session
from app.models.inspection_models import EmailSummary, FollowUpRequest, Inspection, Task

log = logging.getLogger("proofline.email")

BACKEND_DIR = Path(__file__).resolve().parents[2]
OUTBOX_DIR = BACKEND_DIR.parent / "data" / "outbox"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
LABEL = {"DONE": "SUPPORTED", "MISSING": "NOT MET", "CANT_TELL": "NEEDS EVIDENCE"}
ORDER = {"MISSING": 0, "CANT_TELL": 1, "DONE": 2}


def valid_email(address: str) -> bool:
    return len(address) <= 254 and bool(EMAIL_RE.match(address))


def _config() -> Dict[str, str]:
    env = {**dotenv_values(BACKEND_DIR / ".env"), **os.environ}
    return {k: (env.get(k) or "").strip() for k in
            ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "APP_URL")}


def compose(insp: Inspection, tasks, follow_ups, app_url: str, update: bool) -> tuple[str, str]:
    counts = {s: sum(t.status == s for t in tasks) for s in ("DONE", "MISSING", "CANT_TELL")}
    if counts["MISSING"]:
        headline = f"{counts['MISSING']} not met"
    elif counts["CANT_TELL"]:
        headline = f"{counts['CANT_TELL']} need{'s' if counts['CANT_TELL'] == 1 else ''} a photo"
    else:
        headline = "all supported"
    subject = f"{'Updated: ' if update else ''}ProofLine: {insp.title or 'Inspection'} — {headline}"
    request_for = {f.task_id: f.request_text for f in follow_ups if f.status == "PENDING"}
    lines = [f"Inspection report: {insp.title or 'Inspection'}", insp.summary or "", "", "Requirements"]
    for t in sorted(tasks, key=lambda t: ORDER.get(t.status, 3)):
        lines.append(f"  {LABEL.get(t.status, t.status):<15} {t.description}")
        if t.reasoning:
            lines.append(f"  {'':<15} {t.reasoning}")
        if t.id in request_for:
            lines.append(f"  {'':<15} Photo needed: {request_for[t.id]}")
        lines.append("")
    lines += [f"Open the report: {app_url.rstrip('/')}/#/inspections/{insp.id}", "",
              "Findings describe what the submitted photos show. They are not a certification of safety, "
              "code compliance or hidden work."]
    return subject, "\n".join(lines)


def _smtp_send(cfg: Dict[str, str], msg: EmailMessage) -> None:
    port = int(cfg["SMTP_PORT"] or 587)
    if port == 465:
        server = smtplib.SMTP_SSL(cfg["SMTP_HOST"], port, timeout=20)
    else:
        server = smtplib.SMTP(cfg["SMTP_HOST"], port, timeout=20)
        server.starttls()
    with server:
        if cfg["SMTP_USER"]:
            server.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
        server.send_message(msg)


async def send_summary(inspection_id: str, update: bool = False) -> Optional[str]:
    """Write (and if possible send) the summary. Returns the EmailSummary id; never raises."""
    try:
        cfg = _config()
        async with async_session() as session:
            insp = await session.get(Inspection, inspection_id)
            if not insp:
                return None
            tasks = (await session.execute(select(Task).where(Task.inspection_id == inspection_id).order_by(Task.created_at))).scalars().all()
            follow_ups = (await session.execute(select(FollowUpRequest).where(FollowUpRequest.inspection_id == inspection_id))).scalars().all()
            subject, body = compose(insp, tasks, follow_ups, cfg["APP_URL"] or "http://localhost:5173", update)
            row = EmailSummary(inspection_id=inspection_id, to_address=insp.notify_email, subject=subject, body_text=body)
            session.add(row)
            await session.flush()

            msg = EmailMessage()
            msg["Subject"], msg["From"] = subject, cfg["SMTP_FROM"] or "ProofLine <proofline@localhost>"
            if insp.notify_email:
                msg["To"] = insp.notify_email
            msg.set_content(body)
            if cfg["SMTP_HOST"] and insp.notify_email:
                try:
                    await asyncio.to_thread(_smtp_send, cfg, msg)
                    row.status = "SENT"
                except Exception as e:  # delivery problems are recorded, never raised
                    log.warning("email %s for %s not sent: %s", row.id, inspection_id, type(e).__name__)
                    row.status, row.detail = "FAILED", f"Could not send ({type(e).__name__}); kept in the outbox."
            else:
                row.status = "OUTBOX"
                row.detail = ("No email address was given for this inspection." if not insp.notify_email
                              else "SMTP is not configured on this server, so it was kept in the local outbox.")
            if row.status != "SENT":
                OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
                (OUTBOX_DIR / f"{row.id}.eml").write_bytes(bytes(msg))
            await session.commit()
            return row.id
    except Exception:
        log.exception("email summary for %s could not be written", inspection_id)
        return None
