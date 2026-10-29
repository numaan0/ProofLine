from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import Column, DateTime, String, Text, Integer, JSON, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from ..services.persistence import Base


def gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Inspection(Base):
    __tablename__ = "inspections"

    id = Column(String, primary_key=True, default=lambda: gen_id("ins"))
    title = Column(String, nullable=True)
    device_id = Column(String, nullable=True, index=True)  # anonymous browser that created it (app/device.py)
    work_order_text = Column(Text, nullable=False)
    status = Column(String, default="QUEUED")
    overall_outcome = Column(String, nullable=True)
    error_code = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    agent_trace = Column(JSON, nullable=True)  # investigation tool calls: operational record, no model reasoning
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    images = relationship("InspectionImage", back_populates="inspection", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="inspection", cascade="all, delete-orphan")
    observations = relationship("Observation", back_populates="inspection", cascade="all, delete-orphan")
    follow_ups = relationship("FollowUpRequest", back_populates="inspection", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="inspection", cascade="all, delete-orphan")


class InspectionImage(Base):
    __tablename__ = "inspection_images"

    id = Column(String, primary_key=True, default=lambda: gen_id("img"))
    inspection_id = Column(String, ForeignKey("inspections.id"), nullable=False)
    filename = Column(String, nullable=True)
    storage_path = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    validation_state = Column(String, default="PENDING")
    analysis_state = Column(String, default="PENDING")
    role = Column(String, nullable=True)  # "before" for photos of the site before the work; NULL means an after photo
    created_at = Column(DateTime, default=datetime.utcnow)

    inspection = relationship("Inspection", back_populates="images")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: gen_id("task"))
    inspection_id = Column(String, ForeignKey("inspections.id"), nullable=False)
    description = Column(Text, nullable=False)
    observable_criteria = Column(Text, nullable=True)
    status = Column(String, default="CANT_TELL")
    reasoning = Column(Text, nullable=True)
    recommended_action = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    inspection = relationship("Inspection", back_populates="tasks")
    evidence_links = relationship("EvidenceLink", back_populates="task", cascade="all, delete-orphan")
    follow_ups = relationship("FollowUpRequest", back_populates="task", cascade="all, delete-orphan")


class Observation(Base):
    __tablename__ = "observations"

    id = Column(String, primary_key=True, default=lambda: gen_id("obs"))
    inspection_id = Column(String, ForeignKey("inspections.id"), nullable=False)
    image_id = Column(String, ForeignKey("inspection_images.id"), nullable=True)
    relevant_task_ids = Column(JSON, default=list)
    observation_text = Column(Text, nullable=False)
    limitations = Column(Text, nullable=True)
    meta_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    inspection = relationship("Inspection", back_populates="observations")


class EvidenceLink(Base):
    __tablename__ = "evidence_links"

    id = Column(String, primary_key=True, default=lambda: gen_id("ev"))
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False)
    observation_id = Column(String, ForeignKey("observations.id"), nullable=False)
    image_id = Column(String, ForeignKey("inspection_images.id"), nullable=False)
    region = Column(JSON, nullable=True)
    region_source = Column(String, nullable=True)

    task = relationship("Task", back_populates="evidence_links")


class FollowUpRequest(Base):
    __tablename__ = "follow_up_requests"

    id = Column(String, primary_key=True, default=lambda: gen_id("fu"))
    inspection_id = Column(String, ForeignKey("inspections.id"), nullable=False)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=True)
    request_text = Column(Text, nullable=False)
    status = Column(String, default="PENDING")
    linked_follow_up_image_ids = Column(JSON, default=list)
    last_error = Column(Text, nullable=True)  # why the last re-check of follow-up photos could not finish
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    inspection = relationship("Inspection", back_populates="follow_ups")
    task = relationship("Task", back_populates="follow_ups")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=lambda: gen_id("notif"))
    inspection_id = Column(String, ForeignKey("inspections.id"), nullable=True)
    type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    read_state = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    inspection = relationship("Inspection", back_populates="notifications")
