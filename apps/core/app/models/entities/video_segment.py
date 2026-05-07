from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class VideoSegment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    collection_id: int = Field(foreign_key="videocollection.id", index=True)
    job_id: int = Field(foreign_key="job.id", index=True, unique=True)
    sequence_index: int = Field(index=True, ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    source_artifact_id: Optional[int] = Field(default=None, foreign_key="artifact.id", index=True)
    processed_artifact_id: Optional[int] = Field(default=None, foreign_key="artifact.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
