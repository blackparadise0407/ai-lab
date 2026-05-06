from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ConnectedAccountResponse(BaseModel):
    id: int
    platform: str
    provider_account_id: str
    display_name: str
    scopes: str
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ConnectorCallbackResponse(BaseModel):
    connected_account: ConnectedAccountResponse
    status: str = "connected"
