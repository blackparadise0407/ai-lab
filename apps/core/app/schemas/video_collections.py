from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.entities import JobStatus
from app.schemas.jobs import JobResponse


class VideoCollectionCreateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    source_language: str = Field(default="zh", min_length=2, max_length=8)
    target_language: str = Field(default="vi", min_length=2, max_length=8)
    voice_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    output_video_speed: float = Field(default=1.0, gt=0, le=4)
    original_audio_volume: float = Field(default=0.15, ge=0, le=1)
    split_threshold_seconds: int = Field(default=60, ge=1, le=600)


class VideoCollectionResponse(BaseModel):
    id: int
    external_collection_id: str
    title: Optional[str] = None
    original_filename: Optional[str] = None
    source_language: str
    target_language: str
    voice_id: Optional[str] = None
    output_video_speed: float
    original_audio_volume: float
    source_artifact_id: Optional[int] = None
    total_duration_seconds: Optional[float] = None
    split_threshold_seconds: int
    status: JobStatus
    segment_count: int
    completed_segment_count: int
    progress_percent: int
    created_at: datetime
    updated_at: datetime


class VideoSegmentArtifactResponse(BaseModel):
    id: int
    job_id: int
    artifact_type: str
    storage_url: str
    content_type: Optional[str] = None
    created_at: datetime


class VideoSegmentResponse(BaseModel):
    id: int
    collection_id: int
    job_id: int
    sequence_index: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    source_artifact_id: Optional[int] = None
    processed_artifact_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    job: Optional[JobResponse] = None
    source_artifact: Optional[VideoSegmentArtifactResponse] = None
    processed_artifact: Optional[VideoSegmentArtifactResponse] = None


class VideoCollectionDetailResponse(VideoCollectionResponse):
    segments: list[VideoSegmentResponse] = Field(default_factory=list)


class VideoCollectionListResponse(BaseModel):
    items: list[VideoCollectionResponse]
    total: int
    limit: int
    offset: int
