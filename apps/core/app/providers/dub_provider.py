from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request


class DubProviderError(RuntimeError):
    """Raised when dub provider synthesis fails."""


@dataclass(frozen=True)
class TtsChunkRequest:
    chunk_index: int
    text: str
    output_audio: Path
    duration_seconds: float


class DubProviderClient:
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
                "voice_code": os.getenv("DUB_PROVIDER_VOICE_CODE", "hn_female_ngochuyen_full_48k-fhg"),
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
        self._run_cmd(cmd, "silent mock audio generation failed")

    def _run_cmd(self, cmd: list[str], error_message: str) -> None:
        process = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if process.returncode != 0:
            details = process.stderr.strip() or process.stdout.strip()
            raise DubProviderError(f"{error_message}: {details}")
