from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class JobUploadPublishRequest(BaseModel):
    platform: str = Field(..., min_length=2, max_length=32, description="Upload platform key")
    title: str = Field(..., min_length=1, max_length=150)
    description: str = Field(default="", max_length=5000)
    privacy: str = Field(default="private", min_length=3, max_length=32)


class JobUploadPublishResponse(BaseModel):
    job_id: int
    platform: str
    provider_request_id: str
    remote_url: Optional[str] = None
    status: str
