from __future__ import annotations

import json
from unittest.mock import patch

from app.workers.video_processor import VideoProcessingWorker


def test_openai_target_script_prompt_builds_contextual_dub_script() -> None:
    worker = VideoProcessingWorker()
    captured_payload: dict = {}

    class FakeTargetScriptResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "output_text": json.dumps(
                        {
                            "target_language": "Vietnamese",
                            "style_notes": "warm comedy tone",
                            "script": "Xin chào cả nhà. Đi thôi!",
                            "chunks": [
                                {
                                    "index": 0,
                                    "text": "Xin chào cả nhà.",
                                    "source_start": 1.0,
                                    "source_end": 2.0,
                                },
                                {
                                    "index": 1,
                                    "text": "Đi thôi!",
                                    "source_start": 2.5,
                                    "source_end": 3.5,
                                },
                            ],
                            "glossary": [],
                        },
                        ensure_ascii=False,
                    )
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):  # noqa: ANN001
        nonlocal captured_payload
        captured_payload = json.loads(request.data.decode("utf-8"))
        assert timeout == 120
        return FakeTargetScriptResponse()

    source_transcript = {
        "language": "en",
        "segments": [
            {"index": 0, "start": 1.0, "end": 2.0, "text": "Hello everyone."},
            {"index": 1, "start": 2.5, "end": 3.5, "text": "Let's go!"},
        ],
    }

    with patch("urllib.request.urlopen", fake_urlopen):
        script = worker._build_target_script_with_openai(
            openai_api_key="test-key",
            model="test-model",
            target_language="Vietnamese",
            translation_context="wuxia comedy",
            source_transcript=source_transcript,
        )

    system_text = captured_payload["input"][0]["content"][0]["text"]
    user_transcript = json.loads(captured_payload["input"][1]["content"][0]["text"])

    assert script["script"] == "Xin chào cả nhà. Đi thôi!"
    assert len(script["chunks"]) == 2
    assert "professional dubbing translator" in system_text
    assert "meaningful context" in system_text
    assert "wuxia comedy" in system_text
    assert "Vietnamese" in system_text
    assert "pause_after_seconds" not in system_text
    assert "pauses after chunks" not in system_text
    assert user_transcript == source_transcript


def test_normalize_whisper_language_code_accepts_provider_locales() -> None:
    worker = VideoProcessingWorker()

    assert worker._normalize_whisper_language_code("vi-VN") == "vi"
    assert worker._normalize_whisper_language_code("en_US") == "en"
    assert worker._normalize_whisper_language_code("cmn-CN") == "zh"
    assert worker._normalize_whisper_language_code("fil-PH") == "tl"
    assert worker._normalize_whisper_language_code("yue-HK") == "yue"
    assert worker._normalize_whisper_language_code(" nb-NO ") == "no"
    assert worker._normalize_whisper_language_code(None) == ""
