from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ConnectedAccount(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str = Field(index=True, max_length=32)
    provider_account_id: str = Field(index=True, max_length=128)
    display_name: str = Field(max_length=256)
    access_token: str = Field(max_length=4096)
    refresh_token: Optional[str] = Field(default=None, max_length=4096)
    token_type: str = Field(default="Bearer", max_length=32)
    scopes: str = Field(default="", max_length=2048)
    expires_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
