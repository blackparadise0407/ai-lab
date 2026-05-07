from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.entities.enums import JobStatus


class VideoCollection(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    external_collection_id: str = Field(index=True, unique=True, max_length=64)
    title: Optional[str] = Field(default=None, max_length=255)
    original_filename: Optional[str] = Field(default=None, max_length=255)
    source_language: str = Field(default="zh", max_length=8)
    target_language: str = Field(default="vi", max_length=8)
    voice_id: Optional[str] = Field(default=None, max_length=128)
    source_artifact_id: Optional[int] = Field(default=None, foreign_key="artifact.id", index=True)
    total_duration_seconds: Optional[float] = Field(default=None, ge=0)
    split_threshold_seconds: int = Field(default=60, ge=1)
    status: JobStatus = Field(default=JobStatus.CREATED, index=True)
    segment_count: int = Field(default=0, ge=0)
    completed_segment_count: int = Field(default=0, ge=0)
    progress_percent: int = Field(default=0, ge=0, le=100)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
