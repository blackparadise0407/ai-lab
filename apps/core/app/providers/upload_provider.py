from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import http.client
import os
from pathlib import Path
import random
import time
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
import httplib2
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
class UploadCredentials:
    access_token: str | None = None
    refresh_token: str | None = None
    token_uri: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class UploadResult:
    platform: str
    provider_request_id: str
    remote_url: str | None = None


class UploadProviderAdapter(ABC):
    """Adapter interface implemented by each publish destination."""

    platform: str

    @abstractmethod
    def upload(self, request: UploadRequest, credentials: UploadCredentials | None = None) -> UploadResult:
        """Upload a rendered video and return provider tracking metadata."""


class HttpUploadProviderAdapter(UploadProviderAdapter):
    """Base adapter for providers that accept token-authenticated multipart uploads."""

    platform: str
    env_prefix: str
    file_field_name = "video"

    def upload(self, request: UploadRequest, credentials: UploadCredentials | None = None) -> UploadResult:
        if not request.video_path.exists():
            raise UploadProviderError(f"Upload source video does not exist: {request.video_path}")

        upload_url = os.getenv(f"{self.env_prefix}_UPLOAD_URL")
        if not upload_url:
            return self._mock_upload(request)

        access_token = credentials.access_token if credentials else os.getenv(f"{self.env_prefix}_ACCESS_TOKEN")
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

    def _mock_upload(self, request: UploadRequest) -> UploadResult:
        return UploadResult(
            platform=self.platform,
            provider_request_id=f"mock-{self.platform}-{request.job_id}",
            remote_url=f"mock://{self.platform}/jobs/{request.job_id}",
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


class YouTubeUploadAdapter(UploadProviderAdapter):
    platform = "youtube"
    valid_privacy_statuses = {"public", "private", "unlisted"}
    retriable_status_codes = {500, 502, 503, 504}
    retriable_exceptions = (
        httplib2.HttpLib2Error,
        OSError,
        http.client.NotConnected,
        http.client.IncompleteRead,
        http.client.ImproperConnectionState,
        http.client.CannotSendRequest,
        http.client.CannotSendHeader,
        http.client.ResponseNotReady,
        http.client.BadStatusLine,
    )

    def upload(self, request: UploadRequest, credentials: UploadCredentials | None = None) -> UploadResult:
        if not request.video_path.exists():
            raise UploadProviderError(f"Upload source video does not exist: {request.video_path}")
        if not self._is_configured(credentials):
            return UploadResult(
                platform=self.platform,
                provider_request_id=f"mock-{self.platform}-{request.job_id}",
                remote_url=f"mock://{self.platform}/jobs/{request.job_id}",
            )

        privacy_status = self._validate_privacy_status(request.privacy)
        youtube = self._build_youtube_client(credentials)
        response = self._upload_video(youtube, request, privacy_status)
        video_id = response.get("id")
        if not video_id:
            raise UploadProviderError(f"YouTube upload returned an unexpected response: {response}")

        return UploadResult(
            platform=self.platform,
            provider_request_id=str(video_id),
            remote_url=f"https://www.youtube.com/watch?v={video_id}",
        )

    def _is_configured(self, credentials: UploadCredentials | None = None) -> bool:
        if credentials and credentials.access_token:
            return True

        configured_values = [
            os.getenv("YOUTUBE_CLIENT_ID"),
            os.getenv("YOUTUBE_CLIENT_SECRET"),
            os.getenv("YOUTUBE_REFRESH_TOKEN"),
        ]
        if not any(configured_values):
            return False
        if not all(configured_values):
            raise UploadProviderError(
                "YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, and YOUTUBE_REFRESH_TOKEN are required for env-based YouTube uploads"
            )
        return True

    def _validate_privacy_status(self, privacy: str) -> str:
        privacy_status = privacy.strip().lower()
        if privacy_status not in self.valid_privacy_statuses:
            valid_values = ", ".join(sorted(self.valid_privacy_statuses))
            raise UploadProviderError(f"YouTube privacy must be one of: {valid_values}")
        return privacy_status

    def _build_youtube_client(self, upload_credentials: UploadCredentials | None = None):
        scopes = ["https://www.googleapis.com/auth/youtube.upload"]
        if upload_credentials and upload_credentials.access_token:
            credentials = Credentials(
                token=upload_credentials.access_token,
                refresh_token=upload_credentials.refresh_token,
                token_uri=upload_credentials.token_uri or os.getenv("YOUTUBE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
                client_id=upload_credentials.client_id or os.getenv("YOUTUBE_CLIENT_ID"),
                client_secret=upload_credentials.client_secret or os.getenv("YOUTUBE_CLIENT_SECRET"),
                scopes=list(upload_credentials.scopes or tuple(scopes)),
            )
        else:
            credentials = Credentials(
                token=None,
                refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
                token_uri=os.getenv("YOUTUBE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
                client_id=os.environ["YOUTUBE_CLIENT_ID"],
                client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
                scopes=scopes,
            )
        return build("youtube", "v3", credentials=credentials, cache_discovery=False)

    def _upload_video(self, youtube, request: UploadRequest, privacy_status: str) -> dict[str, Any]:
        body = {
            "snippet": {
                "title": request.title,
                "description": request.description,
                "tags": self._get_tags(),
                "categoryId": os.getenv("YOUTUBE_CATEGORY_ID", "22"),
            },
            "status": {"privacyStatus": privacy_status},
        }
        insert_request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=MediaFileUpload(
                str(request.video_path),
                chunksize=self._get_chunk_size(),
                resumable=True,
            ),
        )
        return self._execute_resumable_upload(insert_request)

    def _execute_resumable_upload(self, insert_request) -> dict[str, Any]:
        response = None
        retry = 0
        max_retries = self._get_max_retries()
        while response is None:
            error: str | None = None
            try:
                _status, response = insert_request.next_chunk()
                if response is not None:
                    if isinstance(response, dict):
                        return response
                    raise UploadProviderError(f"YouTube upload returned a non-object response: {response}")
            except HttpError as exc:
                if exc.resp.status in self.retriable_status_codes:
                    error = f"retriable HTTP {exc.resp.status}: {exc.content}"
                else:
                    raise UploadProviderError(f"YouTube upload failed with HTTP {exc.resp.status}: {exc.content}") from exc
            except self.retriable_exceptions as exc:
                error = f"retriable transport error: {exc}"

            if error is not None:
                retry += 1
                if retry > max_retries:
                    raise UploadProviderError(f"YouTube upload failed after {max_retries} retries: {error}")
                time.sleep(random.random() * (2**retry))

        raise UploadProviderError("YouTube upload ended without a response")

    def _get_chunk_size(self) -> int:
        raw_chunk_size = os.getenv("YOUTUBE_UPLOAD_CHUNK_SIZE", "-1")
        try:
            chunk_size = int(raw_chunk_size)
        except ValueError as exc:
            raise UploadProviderError("YOUTUBE_UPLOAD_CHUNK_SIZE must be an integer") from exc
        if chunk_size == 0 or chunk_size < -1:
            raise UploadProviderError("YOUTUBE_UPLOAD_CHUNK_SIZE must be -1 or a positive integer")
        return chunk_size

    def _get_max_retries(self) -> int:
        raw_max_retries = os.getenv("YOUTUBE_UPLOAD_MAX_RETRIES", "10")
        try:
            max_retries = int(raw_max_retries)
        except ValueError as exc:
            raise UploadProviderError("YOUTUBE_UPLOAD_MAX_RETRIES must be an integer") from exc
        if max_retries < 0:
            raise UploadProviderError("YOUTUBE_UPLOAD_MAX_RETRIES must be at least 0")
        return max_retries

    def _get_tags(self) -> list[str]:
        raw_tags = os.getenv("YOUTUBE_TAGS", "")
        return [tag.strip() for tag in raw_tags.split(",") if tag.strip()]


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

    def upload(
        self,
        platform: str,
        request: UploadRequest,
        credentials: UploadCredentials | None = None,
    ) -> UploadResult:
        normalized_platform = platform.strip().lower()
        adapter = self._adapters.get(normalized_platform)
        if not adapter:
            supported = ", ".join(self.supported_platforms)
            raise UploadProviderError(
                f"Unsupported upload platform '{platform}'. Supported platforms: {supported}"
            )
        return adapter.upload(request, credentials=credentials)
