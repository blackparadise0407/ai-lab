from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

from app.utils import run_cmd


class DubProviderError(RuntimeError):
    """Raised when dub provider synthesis fails."""


@dataclass(frozen=True)
class TtsChunkRequest:
    chunk_index: int
    text: str
    output_audio: Path
    duration_seconds: float
    voice_id: str | None = None


@dataclass(frozen=True)
class DubVoice:
    voice_id: str
    name: str
    gender: str | None = None
    language: str | None = None
    accent: str | None = None


@dataclass(frozen=True)
class DubVoiceList:
    voices: list[DubVoice]
    cached: bool
    cache_ttl_seconds: int


class DubProviderClient:
    _voices_cache: list[DubVoice] | None = None
    _voices_cache_expires_at = 0.0
    _voices_cache_lock = threading.Lock()

    def synthesize_chunks(self, job_id: int, chunk_requests: list[TtsChunkRequest]) -> list[str]:
        batch_size = self._get_chunk_batch_size()
        max_attempts = self._get_chunk_max_attempts()
        retry_delay_seconds = self._get_chunk_retry_delay_seconds()
        provider_request_ids = [""] * len(chunk_requests)
        indexed_requests = list(enumerate(chunk_requests))
        for batch_start in range(0, len(indexed_requests), batch_size):
            batch = indexed_requests[batch_start : batch_start + batch_size]
            pending_requests = dict(batch)
            failed_errors: dict[int, Exception] = {}
            for attempt in range(1, max_attempts + 1):
                failed_errors.clear()
                with ThreadPoolExecutor(max_workers=len(pending_requests)) as executor:
                    futures = {
                        executor.submit(self._synthesize_chunk, job_id, chunk_request): (position, chunk_request)
                        for position, chunk_request in pending_requests.items()
                    }
                    for future in as_completed(futures):
                        position, chunk_request = futures[future]
                        try:
                            provider_request_ids[position] = future.result()
                        except Exception as exc:  # noqa: BLE001
                            failed_errors[position] = exc
                        else:
                            pending_requests.pop(position, None)

                if not pending_requests:
                    break
                if attempt < max_attempts:
                    time.sleep(retry_delay_seconds * (2 ** (attempt - 1)))

            if pending_requests:
                failed_chunks = ", ".join(
                    f"{chunk_request.chunk_index}: {failed_errors.get(position)}"
                    for position, chunk_request in sorted(
                        pending_requests.items(), key=lambda item: item[1].chunk_index
                    )
                )
                raise DubProviderError(
                    f"TTS synthesis failed after {max_attempts} attempts for chunk(s) {failed_chunks}"
                )

        return provider_request_ids

    def list_voices(self, force_refresh: bool = False) -> DubVoiceList:
        cache_ttl_seconds = self._get_voices_cache_ttl_seconds()
        now = time.time()
        with self._voices_cache_lock:
            if (
                not force_refresh
                and self._voices_cache is not None
                and now < self._voices_cache_expires_at
            ):
                return DubVoiceList(
                    voices=list(self._voices_cache),
                    cached=True,
                    cache_ttl_seconds=cache_ttl_seconds,
                )

            voices = self._fetch_voices()
            self._voices_cache = voices
            self._voices_cache_expires_at = now + cache_ttl_seconds
            return DubVoiceList(
                voices=list(voices),
                cached=False,
                cache_ttl_seconds=cache_ttl_seconds,
            )

    @classmethod
    def clear_voices_cache(cls) -> None:
        with cls._voices_cache_lock:
            cls._voices_cache = None
            cls._voices_cache_expires_at = 0.0

    def _synthesize_chunk(self, job_id: int, chunk_request: TtsChunkRequest) -> str:
        provider_url = os.getenv("DUB_PROVIDER_URL")
        provider_app_id = os.getenv("DUB_PROVIDER_APP_ID")
        provider_token = os.getenv("DUB_PROVIDER_TOKEN")
        if not provider_url:
            self._create_silent_audio(chunk_request.output_audio, chunk_request.duration_seconds)
            return f"mock-{job_id}-{chunk_request.chunk_index}"
        if not provider_app_id or not provider_token:
            raise DubProviderError(
                "DUB_PROVIDER_APP_ID and DUB_PROVIDER_TOKEN are required when DUB_PROVIDER_URL is set"
            )

        payload = json.dumps(
            {
                "app_id": provider_app_id,
                "input_text": chunk_request.text,
                "audio_type": "wav",
                "response_type": "direct",
                "voice_code": chunk_request.voice_id or self._get_default_voice_id(),
            }
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider_token}",
        }
        create_request = urllib.request.Request(
            provider_url,
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(create_request, timeout=60) as response:  # noqa: S310
                create_response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise DubProviderError(f"Dub provider request failed for chunk {chunk_request.chunk_index}: {exc}") from exc

        provider_request_id = str(
            create_response_data.get("result", {}).get("request_id")
            or f"provider-{job_id}-{chunk_request.chunk_index}"
        )
        audio_url = self._wait_for_audio_url(provider_url, provider_request_id, headers)
        self._download_file(audio_url, chunk_request.output_audio)
        return provider_request_id

    def _fetch_voices(self) -> list[DubVoice]:
        voices_url = os.getenv("DUB_PROVIDER_VOICES_URL", "https://vbee.vn/api/public/v1/voices")
        provider_token = os.getenv("DUB_PROVIDER_TOKEN")
        provider_app_id = os.getenv("DUB_PROVIDER_APP_ID")
        headers = {"Accept": "application/json"}
        if provider_token:
            headers["Authorization"] = f"Bearer {provider_token}"

        url = voices_url
        if provider_app_id and os.getenv("DUB_PROVIDER_VOICES_INCLUDE_APP_ID", "0") == "1":
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode({'app_id': provider_app_id})}"

        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise DubProviderError(f"Dub provider voice list request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise DubProviderError("Dub provider voice list response was not valid JSON") from exc

        voices = self._normalize_voice_response(response_data)
        if not voices:
            raise DubProviderError("Dub provider returned no voices")
        return voices

    def _normalize_voice_response(self, response_data: object) -> list[DubVoice]:
        raw_voices = self._extract_voice_items(response_data)
        voices: list[DubVoice] = []
        for raw_voice in raw_voices:
            if not isinstance(raw_voice, dict):
                continue
            voice_id = self._first_string_value(
                raw_voice,
                "voice_code",
                "voice_id",
                "id",
                "code",
                "value",
            )
            if not voice_id:
                continue
            name = self._first_string_value(raw_voice, "name", "voice_name", "display_name", "label") or voice_id
            voices.append(
                DubVoice(
                    voice_id=voice_id,
                    name=name,
                    gender=self._first_string_value(raw_voice, "gender", "sex"),
                    language=self._first_string_value(raw_voice, "language", "lang", "locale"),
                    accent=self._first_string_value(raw_voice, "accent", "region"),
                )
            )
        return voices

    def _extract_voice_items(self, value: object) -> list[object]:
        if isinstance(value, list):
            return value
        if not isinstance(value, dict):
            return []

        for key in ("voices", "items", "data"):
            nested_value = value.get(key)
            if isinstance(nested_value, list):
                return nested_value
        result = value.get("result")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("voices", "items", "data"):
                nested_value = result.get(key)
                if isinstance(nested_value, list):
                    return nested_value
        return []

    def _first_string_value(self, data: dict[object, object], *keys: str) -> str | None:
        for key in keys:
            value = data.get(key)
            if value is None:
                continue
            string_value = str(value).strip()
            if string_value:
                return string_value
        return None

    def _get_default_voice_id(self) -> str:
        return os.getenv("DUB_PROVIDER_VOICE_CODE", "hn_female_ngochuyen_full_48k-fhg")

    def _get_chunk_batch_size(self) -> int:
        raw_batch_size = os.getenv("DUB_TTS_CHUNK_BATCH_SIZE", "5")
        try:
            batch_size = int(raw_batch_size)
        except ValueError as exc:
            raise DubProviderError("DUB_TTS_CHUNK_BATCH_SIZE must be an integer") from exc
        if batch_size < 1:
            raise DubProviderError("DUB_TTS_CHUNK_BATCH_SIZE must be at least 1")
        return batch_size

    def _get_chunk_max_attempts(self) -> int:
        raw_max_attempts = os.getenv("DUB_TTS_CHUNK_MAX_ATTEMPTS", "3")
        try:
            max_attempts = int(raw_max_attempts)
        except ValueError as exc:
            raise DubProviderError("DUB_TTS_CHUNK_MAX_ATTEMPTS must be an integer") from exc
        if max_attempts < 1:
            raise DubProviderError("DUB_TTS_CHUNK_MAX_ATTEMPTS must be at least 1")
        return max_attempts

    def _get_chunk_retry_delay_seconds(self) -> float:
        raw_retry_delay = os.getenv("DUB_TTS_CHUNK_RETRY_DELAY_SECONDS", "2")
        try:
            retry_delay_seconds = float(raw_retry_delay)
        except ValueError as exc:
            raise DubProviderError("DUB_TTS_CHUNK_RETRY_DELAY_SECONDS must be a number") from exc
        if retry_delay_seconds < 0:
            raise DubProviderError("DUB_TTS_CHUNK_RETRY_DELAY_SECONDS must be at least 0")
        return retry_delay_seconds

    def _get_voices_cache_ttl_seconds(self) -> int:
        raw_cache_ttl = os.getenv("DUB_PROVIDER_VOICES_CACHE_TTL_SECONDS", "86400")
        try:
            cache_ttl_seconds = int(raw_cache_ttl)
        except ValueError as exc:
            raise DubProviderError("DUB_PROVIDER_VOICES_CACHE_TTL_SECONDS must be an integer") from exc
        if cache_ttl_seconds < 1:
            raise DubProviderError("DUB_PROVIDER_VOICES_CACHE_TTL_SECONDS must be at least 1")
        return cache_ttl_seconds

    def _wait_for_audio_url(self, provider_url: str, provider_request_id: str, headers: dict[str, str]) -> str:
        status_url = f"{provider_url.rstrip('/')}/{provider_request_id}"
        for _ in range(30):
            request = urllib.request.Request(status_url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                    status_response_data = json.loads(response.read().decode("utf-8"))
            except urllib.error.URLError as exc:
                raise DubProviderError(f"Dub provider status check failed: {exc}") from exc

            result = status_response_data.get("result", {})
            request_status = result.get("status")
            audio_url = result.get("audio_link")
            if request_status == "SUCCESS" and audio_url:
                return str(audio_url)
            if request_status == "FAILURE":
                raise DubProviderError("Dub provider synthesis request failed")
            time.sleep(2)

        raise DubProviderError("Timed out waiting for dub provider audio")

    def _download_file(self, url: str, output_path: Path) -> None:
        try:
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
                output_path.write_bytes(response.read())
        except urllib.error.URLError as exc:
            raise DubProviderError(f"Failed to download dubbed audio: {exc}") from exc

    def _create_silent_audio(self, output_audio: Path, duration_seconds: float) -> None:
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=mono:sample_rate=48000",
            "-t",
            f"{max(0.1, duration_seconds):.3f}",
            "-c:a",
            "pcm_s16le",
            str(output_audio),
        ]
        run_cmd(cmd, "silent mock audio generation failed", DubProviderError)
