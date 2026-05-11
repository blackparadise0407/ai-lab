from __future__ import annotations

from pathlib import Path

from app.workers.video_processor import VideoProcessingWorker


def test_mux_audio_applies_output_speed_and_original_audio_volume(tmp_path) -> None:
    worker = VideoProcessingWorker()
    captured: dict[str, list[str]] = {}

    def capture_cmd(cmd: list[str], error_message: str) -> None:
        captured["cmd"] = cmd
        captured["error_message"] = [error_message]

    worker._run_cmd = capture_cmd  # type: ignore[method-assign]

    worker._mux_audio(
        Path("source.mp4"),
        Path("dubbed.wav"),
        Path("translated.srt"),
        tmp_path / "output.mp4",
        output_video_speed=1.5,
        original_audio_volume=0.2,
    )

    cmd = captured["cmd"]
    filter_complex = cmd[cmd.index("-filter_complex") + 1]

    assert "setpts=PTS/1.5[vout]" in filter_complex
    assert "[0:a]volume=0.2,atempo=1.5[aoriginal]" in filter_complex
    assert "[1:a]atempo=1.5[adubbed]" in filter_complex
    assert (
        "[aoriginal][adubbed]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]"
        in filter_complex
    )
    assert cmd[cmd.index("-map") + 1] == "[vout]"


def test_tempo_filter_supports_slow_output_speed() -> None:
    worker = VideoProcessingWorker()

    assert worker._build_tempo_filter(0.25) == "atempo=0.5,atempo=0.5"


def test_compile_ssml_from_srt_blocks_inserts_timed_breaks_and_escapes_text() -> None:
    worker = VideoProcessingWorker()

    ssml_text, duration_seconds = worker._compile_ssml_from_srt_blocks(
        [
            ("1", "00:00:01,000 --> 00:00:02,000", "Xin chào & chào mừng"),
            ("2", "00:00:02,200 --> 00:00:03,000", "đến đây"),
            ("3", "00:00:03,750 --> 00:00:04,500", "nhé"),
        ]
    )

    assert ssml_text == "Xin chào &amp; chào mừng đến đây <break time=0.75s/> nhé"
    assert duration_seconds == 3.5


def test_synthesize_dubbed_audio_from_srt_submits_one_compiled_ssml_request(tmp_path) -> None:
    worker = VideoProcessingWorker()
    captured: dict[str, object] = {}

    def synthesize_chunks(job_id, chunk_requests):  # noqa: ANN001
        captured["job_id"] = job_id
        captured["chunk_requests"] = chunk_requests
        return ["provider-request-1"]

    worker._dub_provider.synthesize_chunks = synthesize_chunks  # type: ignore[method-assign]

    output_audio, provider_request_ids = worker._synthesize_dubbed_audio_from_srt(
        42,
        "1\n00:00:01,000 --> 00:00:02,000\nXin chào\n\n"
        "2\n00:00:02,600 --> 00:00:03,500\nđi thôi\n",
        tmp_path,
        voice_id="voice-1",
    )

    chunk_requests = captured["chunk_requests"]
    assert captured["job_id"] == 42
    assert len(chunk_requests) == 1
    assert chunk_requests[0].chunk_index == 1
    assert chunk_requests[0].text == "Xin chào <break time=0.60s/> đi thôi"
    assert chunk_requests[0].output_audio == tmp_path / "dubbed.wav"
    assert chunk_requests[0].duration_seconds == 2.5
    assert chunk_requests[0].voice_id == "voice-1"
    assert output_audio == tmp_path / "dubbed.wav"
    assert provider_request_ids == ["provider-request-1"]
