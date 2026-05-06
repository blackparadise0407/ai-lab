from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import requests


class UploadProviderError(RuntimeError):
    """Raised when an upload provider cannot publish a video."""


@dataclass(frozen=True)
class UploadRequest:
    job_id: int
    video_path: Path
    title: str
    description: str = ""
    privacy: str = "private"


@dataclass(frozen=True)
class UploadResult:
    platform: str
    provider_request_id: str
    remote_url: str | None = None


class UploadProviderAdapter(ABC):
    """Adapter interface implemented by each publish destination."""

    platform: str

    @abstractmethod
    def upload(self, request: UploadRequest) -> UploadResult:
        """Upload a rendered video and return provider tracking metadata."""


class HttpUploadProviderAdapter(UploadProviderAdapter):
    """Base adapter for providers that accept token-authenticated multipart uploads."""

    platform: str
    env_prefix: str
    file_field_name = "video"

    def upload(self, request: UploadRequest) -> UploadResult:
        if not request.video_path.exists():
            raise UploadProviderError(f"Upload source video does not exist: {request.video_path}")

        upload_url = os.getenv(f"{self.env_prefix}_UPLOAD_URL")
        if not upload_url:
            return UploadResult(
                platform=self.platform,
                provider_request_id=f"mock-{self.platform}-{request.job_id}",
                remote_url=f"mock://{self.platform}/jobs/{request.job_id}",
            )

        access_token = os.getenv(f"{self.env_prefix}_ACCESS_TOKEN")
        if not access_token:
            raise UploadProviderError(
                f"{self.env_prefix}_ACCESS_TOKEN is required when {self.env_prefix}_UPLOAD_URL is set"
            )

        response_data = self._post_multipart(upload_url, access_token, request)
        provider_request_id = self._extract_provider_request_id(response_data, request)
        remote_url = self._extract_remote_url(response_data)
        return UploadResult(
            platform=self.platform,
            provider_request_id=provider_request_id,
            remote_url=remote_url,
        )

    def _post_multipart(self, upload_url: str, access_token: str, request: UploadRequest) -> dict[str, Any]:
        data = self._build_metadata(request)
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            with request.video_path.open("rb") as video_file:
                response = requests.post(
                    upload_url,
                    headers=headers,
                    data=data,
                    files={self.file_field_name: (request.video_path.name, video_file, "video/mp4")},
                    timeout=300,
                )
        except requests.RequestException as exc:
            raise UploadProviderError(f"{self.platform} upload request failed: {exc}") from exc

        if response.status_code >= 400:
            raise UploadProviderError(
                f"{self.platform} upload failed with HTTP {response.status_code}: {response.text[:512]}"
            )

        if not response.content:
            return {}

        try:
            parsed = response.json()
        except ValueError as exc:
            raise UploadProviderError(f"{self.platform} upload response was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise UploadProviderError(f"{self.platform} upload response must be a JSON object")
        return parsed

    def _build_metadata(self, request: UploadRequest) -> dict[str, str]:
        return {
            "title": request.title,
            "description": request.description,
            "privacy": request.privacy,
        }

    def _extract_provider_request_id(self, response_data: dict[str, Any], request: UploadRequest) -> str:
        raw_id = (
            response_data.get("id")
            or response_data.get("video_id")
            or response_data.get("request_id")
            or response_data.get("upload_id")
        )
        return str(raw_id or f"{self.platform}-{request.job_id}")

    def _extract_remote_url(self, response_data: dict[str, Any]) -> str | None:
        raw_url = response_data.get("url") or response_data.get("permalink_url") or response_data.get("share_url")
        if raw_url is None:
            return None
        return str(raw_url)


class YouTubeUploadAdapter(HttpUploadProviderAdapter):
    platform = "youtube"
    env_prefix = "YOUTUBE"
    file_field_name = "file"

    def _build_metadata(self, request: UploadRequest) -> dict[str, str]:
        metadata = super()._build_metadata(request)
        metadata["status.privacyStatus"] = request.privacy
        return metadata


class FacebookUploadAdapter(HttpUploadProviderAdapter):
    platform = "facebook"
    env_prefix = "FACEBOOK"
    file_field_name = "source"


class TikTokUploadAdapter(HttpUploadProviderAdapter):
    platform = "tiktok"
    env_prefix = "TIKTOK"
    file_field_name = "video"


class UploadProviderClient:
    def __init__(self, adapters: list[UploadProviderAdapter] | None = None) -> None:
        configured_adapters = adapters or [
            YouTubeUploadAdapter(),
            FacebookUploadAdapter(),
            TikTokUploadAdapter(),
        ]
        self._adapters = {adapter.platform: adapter for adapter in configured_adapters}

    @property
    def supported_platforms(self) -> tuple[str, ...]:
        return tuple(self._adapters.keys())

    def upload(self, platform: str, request: UploadRequest) -> UploadResult:
        normalized_platform = platform.strip().lower()
        adapter = self._adapters.get(normalized_platform)
        if not adapter:
            supported = ", ".join(self.supported_platforms)
            raise UploadProviderError(
                f"Unsupported upload platform '{platform}'. Supported platforms: {supported}"
            )
        return adapter.upload(request)
