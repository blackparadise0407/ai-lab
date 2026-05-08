from pydantic import BaseModel, Field


class DubVoiceResponse(BaseModel):
    voice_id: str
    name: str
    gender: str | None = None
    language: str | None = None
    accent: str | None = None
    credit_factor: float | None = None
    demo: str | None = None


class DubVoiceListResponse(BaseModel):
    items: list[DubVoiceResponse]
    cached: bool
    cache_ttl_seconds: int = Field(ge=1)
