from __future__ import annotations

import json
from unittest.mock import patch

from app.workers.video_processor import VideoProcessingWorker


class FakeOpenAIResponse:
    def __enter__(self) -> "FakeOpenAIResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        return None

    def read(self) -> bytes:
        return json.dumps({"output_text": json.dumps(["Xin chào", "Đi thôi"])}).encode(
            "utf-8"
        )


def test_build_translation_cues_includes_srt_timing_and_duration() -> None:
    worker = VideoProcessingWorker()

    cues = worker._build_translation_cues(
        [
            ("1", "00:00:01,000 --> 00:00:02,250", "Hello there"),
            ("2", "00:00:03,500 --> 00:00:06,000", "Let's go"),
        ]
    )

    assert cues == [
        {
            "index": 0,
            "timing": "00:00:01,000 --> 00:00:02,250",
            "duration_seconds": 1.25,
            "break_after_seconds": 1.25,
            "text": "Hello there",
        },
        {
            "index": 1,
            "timing": "00:00:03,500 --> 00:00:06,000",
            "duration_seconds": 2.5,
            "break_after_seconds": 0.0,
            "text": "Let's go",
        },
    ]


def test_openai_translation_prompt_prioritizes_dubbing_timing_and_context() -> None:
    worker = VideoProcessingWorker()
    captured_payload: dict = {}

    def fake_urlopen(request, timeout):  # noqa: ANN001
        nonlocal captured_payload
        captured_payload = json.loads(request.data.decode("utf-8"))
        assert timeout == 90
        return FakeOpenAIResponse()

    cues = [
        {
            "index": 0,
            "timing": "00:00:01,000 --> 00:00:02,250",
            "duration_seconds": 1.25,
            "break_after_seconds": 1.25,
            "text": "Hello there",
        },
        {
            "index": 1,
            "timing": "00:00:03,500 --> 00:00:06,000",
            "duration_seconds": 2.5,
            "break_after_seconds": 0.0,
            "text": "Let's go",
        },
    ]

    with patch("urllib.request.urlopen", fake_urlopen):
        translated = worker._translate_cues_with_openai(
            openai_api_key="test-key",
            model="test-model",
            target_language="Vietnamese",
            translation_context="wuxia comedy",
            cues=cues,
        )

    system_text = captured_payload["input"][0]["content"][0]["text"]
    user_cues = json.loads(captured_payload["input"][1]["content"][0]["text"])

    assert translated == ["Xin chào", "Đi thôi"]
    assert "professional Subtitle Translator and Dubbing Script Editor" in system_text
    assert (
        "Read the entire ordered cue list as one continuous dubbing script"
        in system_text
    )
    assert "break_after_seconds" in system_text
    assert "<break time={seconds:.2f}s/>" in system_text
    assert 'The "Dubbing" Constraint (Timing is King)' in system_text
    assert "Timing and brevity > literal accuracy" in system_text
    assert "Sentence Continuity" in system_text
    assert "SSML Break Awareness" in system_text
    assert "Non-Speech Elements" in system_text
    assert "wuxia comedy" in system_text
    assert "Vietnamese" in system_text
    assert user_cues == cues


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
                                    "pause_after_seconds": 0.5,
                                },
                                {
                                    "index": 1,
                                    "text": "Đi thôi!",
                                    "source_start": 2.5,
                                    "source_end": 3.5,
                                    "pause_after_seconds": 0,
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
