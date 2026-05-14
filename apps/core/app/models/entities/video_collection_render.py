from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.entities.enums import JobStatus


class VideoCollectionRender(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    collection_id: int = Field(foreign_key="videocollection.id", index=True)
    status: JobStatus = Field(default=JobStatus.CREATED, index=True)
    current_step: str = Field(default="created", max_length=128)
    progress_percent: int = Field(default=0, ge=0, le=100)
    included_segment_ids: str = Field(default="", max_length=2048)
    output_path: Optional[str] = Field(default=None, max_length=2048)
    content_type: str = Field(default="video/mp4", max_length=128)
    duration_seconds: Optional[float] = Field(default=None, ge=0)
    error_message: Optional[str] = Field(default=None, max_length=2048)
    published_platform: Optional[str] = Field(default=None, max_length=64)
    provider_request_id: Optional[str] = Field(default=None, max_length=255)
    remote_url: Optional[str] = Field(default=None, max_length=2048)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
