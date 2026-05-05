from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Artifact(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    artifact_type: str = Field(index=True, max_length=32)
    storage_url: str = Field(max_length=2048)
    content_type: Optional[str] = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
