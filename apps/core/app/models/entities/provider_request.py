from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.entities.enums import ProviderRequestStatus


class ProviderRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    provider_name: str = Field(max_length=64)
    provider_request_id: str = Field(index=True, unique=True, max_length=128)
    status: ProviderRequestStatus = Field(default=ProviderRequestStatus.PENDING, index=True)
    callback_received: bool = Field(default=False)
    retry_count: int = Field(default=0, ge=0)
    last_error: Optional[str] = Field(default=None, max_length=1024)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
