from __future__ import annotations

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
