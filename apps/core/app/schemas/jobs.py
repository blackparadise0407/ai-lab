from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.entities import JobStatus


class JobCreateRequest(BaseModel):
    source_language: str = Field(default="zh", min_length=2, max_length=8)
    target_language: str = Field(default="vi", min_length=2, max_length=8)


class JobResponse(BaseModel):
    id: int
    external_job_id: str
    source_language: str
    target_language: str
    status: JobStatus
    current_step: Optional[str] = None
    progress_percent: int
    created_at: datetime
    updated_at: datetime
