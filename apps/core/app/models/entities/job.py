from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.entities.enums import JobStatus


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    external_job_id: str = Field(index=True, unique=True, max_length=64)
    source_language: str = Field(default="zh", max_length=8)
    target_language: str = Field(default="vi", max_length=8)
    voice_id: Optional[str] = Field(default=None, max_length=128)
    output_video_speed: float = Field(default=1.0, gt=0, le=4)
    original_audio_volume: float = Field(default=0.15, ge=0, le=1)
    status: JobStatus = Field(default=JobStatus.CREATED, index=True)
    current_step: Optional[str] = Field(default=None, max_length=64)
    progress_percent: int = Field(default=0, ge=0, le=100)
    error_code: Optional[str] = Field(default=None, max_length=64)
    error_message: Optional[str] = Field(default=None, max_length=1024)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
