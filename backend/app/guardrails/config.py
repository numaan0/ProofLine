from __future__ import annotations

import os
from typing import Any, Dict

from pydantic import BaseModel, Field


class WorkOrderPreflightResult(BaseModel):
    classification: str = Field(pattern="^(ACCEPT|CLARIFY|REJECT)$")
    reason: str
    suggestion: str


class PhotoPreflightResult(BaseModel):
    classification: str = Field(pattern="^(USABLE|LOW_QUALITY|IRRELEVANT|NOT_A_PHOTO|INCONCLUSIVE)$")
    reason: str
    action: str = ""


class TaskOutput(BaseModel):
    id: int
    description: str
    status: str = Field(pattern="^(DONE|MISSING|CANT_TELL)$")
    reasoning: str
    evidence: list = Field(default_factory=list)


class InspectionOutput(BaseModel):
    tasks: list[TaskOutput]
    summary: str
    images_processed: int = Field(ge=0)


class GuardrailConfig:
    def __init__(self) -> None:
        self.max_work_order_chars = int(os.getenv("GUARD_MAX_WORK_ORDER_CHARS", "4000"))
        self.min_work_order_chars = int(os.getenv("GUARD_MIN_WORK_ORDER_CHARS", "3"))
        self.max_files = int(os.getenv("GUARD_MAX_FILES", "10"))
        self.max_file_bytes = int(os.getenv("GUARD_MAX_FILE_BYTES", str(10 * 1024 * 1024)))
        self.max_total_bytes = int(os.getenv("GUARD_MAX_TOTAL_BYTES", str(50 * 1024 * 1024)))
        self.min_image_width = int(os.getenv("GUARD_MIN_IMAGE_WIDTH", "64"))
        self.min_image_height = int(os.getenv("GUARD_MIN_IMAGE_HEIGHT", "64"))
        self.enable_semantic_preflight = os.getenv("GUARD_ENABLE_SEMANTIC_PREFLIGHT", "true").lower() == "true"
        self.preflight_timeout = float(os.getenv("GUARD_PREFLIGHT_TIMEOUT", "30"))


config = GuardrailConfig()
