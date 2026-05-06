from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.providers.upload_provider import (
    FacebookUploadAdapter,
    TikTokUploadAdapter,
    UploadCredentials,
    UploadProviderClient,
    UploadProviderError,
    UploadRequest,
    YouTubeUploadAdapter,
)


class FakeYouTubeInsertRequest:
    def __init__(self, response: dict[str, str]) -> None:
        self.response = response
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        return None, self.response


class FakeYouTubeVideosResource:
    def __init__(self, response: dict[str, str]) -> None:
        self.response = response
        self.insert_kwargs = None
        self.insert_request = FakeYouTubeInsertRequest(response)

    def insert(self, **kwargs):
        self.insert_kwargs = kwargs
        return self.insert_request


class FakeYouTubeClient:
    def __init__(self, response: dict[str, str]) -> None:
        self.videos_resource = FakeYouTubeVideosResource(response)

    def videos(self):
        return self.videos_resource


class UploadProviderClientTests(unittest.TestCase):
    def test_supports_initial_platform_adapters(self) -> None:
        client = UploadProviderClient()

        self.assertEqual(client.supported_platforms, ("youtube", "facebook", "tiktok"))

    def test_uses_mock_upload_when_youtube_credentials_are_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "dubbed.mp4"
            video_path.write_bytes(b"video")

            with patch.dict("os.environ", {}, clear=True):
                result = UploadProviderClient().upload(
                    "YouTube",
                    UploadRequest(job_id=42, video_path=video_path, title="Dubbed video"),
                )

        self.assertEqual(result.platform, "youtube")
        self.assertEqual(result.provider_request_id, "mock-youtube-42")
        self.assertEqual(result.remote_url, "mock://youtube/jobs/42")

    def test_rejects_unsupported_platform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "dubbed.mp4"
            video_path.write_bytes(b"video")

            with self.assertRaisesRegex(UploadProviderError, "Unsupported upload platform"):
                UploadProviderClient().upload(
                    "vimeo",
                    UploadRequest(job_id=42, video_path=video_path, title="Dubbed video"),
                )


class UploadProviderAdapterTests(unittest.TestCase):
    def test_requires_token_when_upload_url_is_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "dubbed.mp4"
            video_path.write_bytes(b"video")

            with patch.dict("os.environ", {"TIKTOK_UPLOAD_URL": "https://example.test/upload"}, clear=True):
                with self.assertRaisesRegex(UploadProviderError, "TIKTOK_ACCESS_TOKEN"):
                    TikTokUploadAdapter().upload(
                        UploadRequest(job_id=42, video_path=video_path, title="Dubbed video"),
                    )

    def test_posts_platform_specific_multipart_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "dubbed.mp4"
            video_path.write_bytes(b"video")
            response = Mock(status_code=200, content=b'{"id":"fb-123","url":"https://facebook.test/fb-123"}')
            response.json.return_value = {"id": "fb-123", "url": "https://facebook.test/fb-123"}

            with patch.dict(
                "os.environ",
                {
                    "FACEBOOK_UPLOAD_URL": "https://facebook.example/upload",
                    "FACEBOOK_ACCESS_TOKEN": "token-123",
                },
                clear=True,
            ), patch("app.providers.upload_provider.requests.post", return_value=response) as post:
                result = FacebookUploadAdapter().upload(
                    UploadRequest(
                        job_id=42,
                        video_path=video_path,
                        title="Dubbed video",
                        description="Published by AI Lab",
                        privacy="private",
                    )
                )

        self.assertEqual(result.provider_request_id, "fb-123")
        self.assertEqual(result.remote_url, "https://facebook.test/fb-123")
        _, kwargs = post.call_args
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer token-123"})
        self.assertEqual(kwargs["data"]["title"], "Dubbed video")
        self.assertEqual(kwargs["data"]["privacy"], "private")
        self.assertIn("source", kwargs["files"])


class YouTubeUploadAdapterTests(unittest.TestCase):
    def test_requires_full_oauth_configuration_when_any_youtube_credential_is_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "dubbed.mp4"
            video_path.write_bytes(b"video")

            with patch.dict("os.environ", {"YOUTUBE_CLIENT_ID": "client-id"}, clear=True):
                with self.assertRaisesRegex(UploadProviderError, "YOUTUBE_CLIENT_ID.*YOUTUBE_CLIENT_SECRET"):
                    YouTubeUploadAdapter().upload(
                        UploadRequest(job_id=42, video_path=video_path, title="Dubbed video"),
                    )

    def test_uploads_with_youtube_data_api_video_resource(self) -> None:
        fake_youtube = FakeYouTubeClient({"id": "yt-123"})

        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "dubbed.mp4"
            video_path.write_bytes(b"video")

            with patch.dict(
                "os.environ",
                {
                    "YOUTUBE_CLIENT_ID": "client-id",
                    "YOUTUBE_CLIENT_SECRET": "client-secret",
                    "YOUTUBE_REFRESH_TOKEN": "refresh-token",
                    "YOUTUBE_TAGS": "dubbed, ai lab",
                    "YOUTUBE_UPLOAD_CHUNK_SIZE": "1048576",
                },
                clear=True,
            ), patch.object(YouTubeUploadAdapter, "_build_youtube_client", return_value=fake_youtube):
                result = YouTubeUploadAdapter().upload(
                    UploadRequest(
                        job_id=42,
                        video_path=video_path,
                        title="Dubbed video",
                        description="Published by AI Lab",
                        privacy="unlisted",
                    )
                )

        self.assertEqual(result.provider_request_id, "yt-123")
        self.assertEqual(result.remote_url, "https://www.youtube.com/watch?v=yt-123")
        insert_kwargs = fake_youtube.videos_resource.insert_kwargs
        self.assertEqual(insert_kwargs["part"], "snippet,status")
        self.assertEqual(insert_kwargs["body"]["snippet"]["title"], "Dubbed video")
        self.assertEqual(insert_kwargs["body"]["snippet"]["description"], "Published by AI Lab")
        self.assertEqual(insert_kwargs["body"]["snippet"]["tags"], ["dubbed", "ai lab"])
        self.assertEqual(insert_kwargs["body"]["status"]["privacyStatus"], "unlisted")
        self.assertEqual(fake_youtube.videos_resource.insert_request.calls, 1)


    def test_uploads_with_runtime_youtube_credentials(self) -> None:
        fake_youtube = FakeYouTubeClient({"id": "yt-runtime"})

        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "dubbed.mp4"
            video_path.write_bytes(b"video")

            with patch.dict("os.environ", {}, clear=True), patch.object(
                YouTubeUploadAdapter, "_build_youtube_client", return_value=fake_youtube
            ) as build_client:
                result = YouTubeUploadAdapter().upload(
                    UploadRequest(job_id=42, video_path=video_path, title="Dubbed video"),
                    credentials=UploadCredentials(
                        access_token="access-token",
                        refresh_token="refresh-token",
                        scopes=("https://www.googleapis.com/auth/youtube.upload",),
                    ),
                )

        self.assertEqual(result.provider_request_id, "yt-runtime")
        passed_credentials = build_client.call_args.args[0]
        self.assertEqual(passed_credentials.access_token, "access-token")

    def test_rejects_invalid_youtube_privacy_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "dubbed.mp4"
            video_path.write_bytes(b"video")

            with patch.dict(
                "os.environ",
                {
                    "YOUTUBE_CLIENT_ID": "client-id",
                    "YOUTUBE_CLIENT_SECRET": "client-secret",
                    "YOUTUBE_REFRESH_TOKEN": "refresh-token",
                },
                clear=True,
            ):
                with self.assertRaisesRegex(UploadProviderError, "YouTube privacy"):
                    YouTubeUploadAdapter().upload(
                        UploadRequest(job_id=42, video_path=video_path, title="Dubbed video", privacy="friends"),
                    )


if __name__ == "__main__":
    unittest.main()
