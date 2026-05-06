from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ConnectorState(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str = Field(index=True, max_length=32)
    state: str = Field(index=True, unique=True, max_length=128)
    redirect_after: Optional[str] = Field(default=None, max_length=2048)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    consumed_at: Optional[datetime] = Field(default=None, index=True)
