from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.entities import JobStatus

WhisperModelName = Literal["tiny", "base", "small", "medium", "large-v3", "turbo"]


class JobCreateRequest(BaseModel):
    source_language: str = Field(default="zh", min_length=2, max_length=8)
    target_language: str = Field(default="vi", min_length=2, max_length=8)
    model_name: WhisperModelName = "medium"
    translation_context: Optional[str] = Field(default=None, max_length=100)
    voice_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    output_video_speed: float = Field(default=1.0, gt=0, le=4)
    original_audio_volume: float = Field(default=0.15, ge=0, le=1)

    @field_validator("translation_context", mode="before")
    @classmethod
    def normalize_translation_context(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class JobResponse(BaseModel):
    id: int
    external_job_id: str
    source_language: str
    target_language: str
    model_name: str
    translation_context: Optional[str] = None
    voice_id: Optional[str] = None
    output_video_speed: float
    original_audio_volume: float
    status: JobStatus
    current_step: Optional[str] = None
    progress_percent: int
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int
