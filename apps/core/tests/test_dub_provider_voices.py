from __future__ import annotations

import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app.providers.dub_provider import DubProviderClient


class MockResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_list_voices_normalizes_and_caches_provider_response() -> None:
    DubProviderClient.clear_voices_cache()
    client = DubProviderClient()
    provider_payload = {
        "status": 1,
        "result": {
            "voices": [
                {
                    "voice_code": "voice-one",
                    "name": "Voice One",
                    "gender": "female",
                    "language": "vi",
                    "accent": "northern",
                    "credit_factor": 2,
                    "demo": "https://example.com/demo.mp3",
                }
            ]
        },
    }

    with patch.dict(
        "os.environ", {"DUB_PROVIDER_VOICES_CACHE_TTL_SECONDS": "3600"}, clear=False
    ):
        with patch(
            "urllib.request.urlopen", return_value=MockResponse(provider_payload)
        ) as urlopen_mock:
            first_result = client.list_voices()
            second_result = client.list_voices()

    requested_url = urlopen_mock.call_args.args[0].full_url
    requested_query = parse_qs(urlparse(requested_url).query)

    assert urlopen_mock.call_count == 1
    assert requested_query["language_code"] == ["vi-VN"]
    assert first_result.cached is False
    assert second_result.cached is True
    assert first_result.voices[0].voice_id == "voice-one"
    assert first_result.voices[0].name == "Voice One"
    assert first_result.voices[0].gender == "female"
    assert first_result.voices[0].language == "vi"
    assert first_result.voices[0].accent == "northern"
    assert first_result.voices[0].credit_factor == 2
    assert first_result.voices[0].demo == "https://example.com/demo.mp3"


def test_list_voices_force_refresh_bypasses_cache() -> None:
    DubProviderClient.clear_voices_cache()
    client = DubProviderClient()
    responses = [
        MockResponse({"data": [{"voice_id": "first", "voice_name": "First"}]}),
        MockResponse({"data": [{"voice_id": "second", "voice_name": "Second"}]}),
    ]

    with patch("urllib.request.urlopen", side_effect=responses) as urlopen_mock:
        client.list_voices()
        refreshed_result = client.list_voices(force_refresh=True)

    assert urlopen_mock.call_count == 2
    assert refreshed_result.cached is False
    assert refreshed_result.voices[0].voice_id == "second"


def test_list_voices_caches_provider_response_by_language_code() -> None:
    DubProviderClient.clear_voices_cache()
    client = DubProviderClient()
    responses = [
        MockResponse(
            {"data": [{"voice_id": "vietnamese", "voice_name": "Vietnamese"}]}
        ),
        MockResponse({"data": [{"voice_id": "english", "voice_name": "English"}]}),
    ]

    with patch("urllib.request.urlopen", side_effect=responses) as urlopen_mock:
        vi_result = client.list_voices(language_code="vi-VN")
        en_result = client.list_voices(language_code="en-US")
        cached_vi_result = client.list_voices(language_code="vi-VN")

    requested_urls = [call.args[0].full_url for call in urlopen_mock.call_args_list]
    requested_language_codes = [
        parse_qs(urlparse(url).query)["language_code"] for url in requested_urls
    ]

    assert urlopen_mock.call_count == 2
    assert requested_language_codes == [["vi-VN"], ["en-US"]]
    assert vi_result.cached is False
    assert en_result.cached is False
    assert cached_vi_result.cached is True
    assert cached_vi_result.voices[0].voice_id == "vietnamese"
