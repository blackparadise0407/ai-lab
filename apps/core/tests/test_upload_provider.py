from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.providers.upload_provider import (
    TikTokUploadAdapter,
    UploadProviderClient,
    UploadProviderError,
    UploadRequest,
    YouTubeUploadAdapter,
)


class UploadProviderClientTests(unittest.TestCase):
    def test_supports_initial_platform_adapters(self) -> None:
        client = UploadProviderClient()

        self.assertEqual(client.supported_platforms, ("youtube", "facebook", "tiktok"))

    def test_uses_mock_upload_when_platform_url_is_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "dubbed.mp4"
            video_path.write_bytes(b"video")

            with patch.dict("os.environ", {"YOUTUBE_UPLOAD_URL": ""}, clear=False):
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
            response = Mock(status_code=200, content=b'{"id":"yt-123","url":"https://youtu.be/yt-123"}')
            response.json.return_value = {"id": "yt-123", "url": "https://youtu.be/yt-123"}

            with patch.dict(
                "os.environ",
                {
                    "YOUTUBE_UPLOAD_URL": "https://youtube.example/upload",
                    "YOUTUBE_ACCESS_TOKEN": "token-123",
                },
                clear=True,
            ), patch("app.providers.upload_provider.requests.post", return_value=response) as post:
                result = YouTubeUploadAdapter().upload(
                    UploadRequest(
                        job_id=42,
                        video_path=video_path,
                        title="Dubbed video",
                        description="Published by AI Lab",
                        privacy="private",
                    )
                )

        self.assertEqual(result.provider_request_id, "yt-123")
        self.assertEqual(result.remote_url, "https://youtu.be/yt-123")
        _, kwargs = post.call_args
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer token-123"})
        self.assertEqual(kwargs["data"]["title"], "Dubbed video")
        self.assertEqual(kwargs["data"]["status.privacyStatus"], "private")
        self.assertIn("file", kwargs["files"])


if __name__ == "__main__":
    unittest.main()
