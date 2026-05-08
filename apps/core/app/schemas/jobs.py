from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.entities import JobStatus


class JobCreateRequest(BaseModel):
    source_language: str = Field(default="zh", min_length=2, max_length=8)
    target_language: str = Field(default="vi", min_length=2, max_length=8)
    voice_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    output_video_speed: float = Field(default=1.0, gt=0, le=4)
    original_audio_volume: float = Field(default=0.15, ge=0, le=1)


class JobResponse(BaseModel):
    id: int
    external_job_id: str
    source_language: str
    target_language: str
    voice_id: Optional[str] = None
    output_video_speed: float
    original_audio_volume: float
    status: JobStatus
    current_step: Optional[str] = None
    progress_percent: int
    created_at: datetime
    updated_at: datetime


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int
