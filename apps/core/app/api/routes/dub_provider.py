from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from app.providers.dub_provider import DubProviderClient, DubProviderError
from app.schemas.dub_provider import DubVoiceListResponse

router = APIRouter(prefix="/v1/dub-provider", tags=["dub_provider"])

dub_provider_client = DubProviderClient()


@router.get(
    "/voices",
    response_model=DubVoiceListResponse,
    summary="List TTS provider voices",
    description="Proxies and caches the Vbee public voice list so the browser never calls the provider directly.",
)
async def list_dub_provider_voices(
    refresh: bool = Query(
        default=False, description="Bypass the cached provider voice list."
    ),
    language_code: str = Query(
        default="vi-VN",
        min_length=2,
        max_length=16,
        description="Provider language code used to filter the voice list.",
    ),
):
    try:
        voice_list = await run_in_threadpool(
            dub_provider_client.list_voices, refresh, language_code
        )
    except DubProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "items": voice_list.voices,
        "cached": voice_list.cached,
        "cache_ttl_seconds": voice_list.cache_ttl_seconds,
    }
