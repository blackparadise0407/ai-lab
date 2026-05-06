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
        return json.dumps({"output_text": json.dumps(["Xin chào", "Đi thôi"])}).encode("utf-8")


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
            "text": "Hello there",
        },
        {
            "index": 1,
            "timing": "00:00:03,500 --> 00:00:06,000",
            "duration_seconds": 2.5,
            "text": "Let's go",
        },
    ]


def test_openai_translation_prompt_prioritizes_timestamp_fit_and_natural_coherence() -> None:
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
            "text": "Hello there",
        },
        {
            "index": 1,
            "timing": "00:00:03,500 --> 00:00:06,000",
            "duration_seconds": 2.5,
            "text": "Let's go",
        },
    ]

    with patch("urllib.request.urlopen", fake_urlopen):
        translated = worker._translate_cues_with_openai(
            openai_api_key="test-key",
            model="test-model",
            target_language="Vietnamese",
            cues=cues,
        )

    system_text = captured_payload["input"][0]["content"][0]["text"]
    user_cues = json.loads(captured_payload["input"][1]["content"][0]["text"])

    assert translated == ["Xin chào", "Đi thôi"]
    assert "TIMESTAMP FIT (highest priority)" in system_text
    assert "duration_seconds" in system_text
    assert "NATURALNESS AND COHERENCE" in system_text
    assert "Vietnamese" in system_text
    assert user_cues == cues
