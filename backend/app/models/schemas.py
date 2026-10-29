from pydantic import BaseModel
from typing import List, Optional

class Task(BaseModel):
    id: int
    description: str
    status: str = "PENDING"
    reasoning: str = ""
    evidence: List[str] = []

class InspectionRequest(BaseModel):
    work_order_text: str

class InspectionResult(BaseModel):
    tasks: List[Task]
    summary: str
    images_processed: int