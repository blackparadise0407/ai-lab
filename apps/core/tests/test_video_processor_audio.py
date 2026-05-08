from __future__ import annotations

from pathlib import Path

from app.workers.video_processor import VideoProcessingWorker


def capture_merge_filter(worker: VideoProcessingWorker, tmp_path: Path) -> str:
    captured: dict[str, list[str]] = {}

    def capture_cmd(cmd: list[str], error_message: str) -> None:
        captured["cmd"] = cmd
        captured["error_message"] = [error_message]

    worker._run_cmd = capture_cmd  # type: ignore[method-assign]

    worker._merge_tts_chunks(
        [
            (0.0, 1.0, Path("chunk_0001.wav")),
            (1.0, 2.0, Path("chunk_0002.wav")),
            (2.0, 3.0, Path("chunk_0003.wav")),
        ],
        tmp_path / "dubbed.wav",
    )

    return captured["cmd"][captured["cmd"].index("-filter_complex") + 1]


def test_merge_tts_chunks_disables_amix_normalization_to_prevent_volume_ramp(tmp_path) -> None:
    worker = VideoProcessingWorker()
    worker._probe_audio_duration_seconds = lambda _chunk_path: 1.0  # type: ignore[method-assign]

    filter_complex = capture_merge_filter(worker, tmp_path)

    assert "amix=inputs=3:duration=longest:dropout_transition=0:normalize=0" in filter_complex


def test_merge_tts_chunks_speeds_up_long_chunks_without_pitch_shift(tmp_path) -> None:
    worker = VideoProcessingWorker()
    durations = {
        Path("chunk_0001.wav"): 1.0,
        Path("chunk_0002.wav"): 1.5,
        Path("chunk_0003.wav"): 4.5,
    }
    worker._probe_audio_duration_seconds = lambda chunk_path: durations[chunk_path]  # type: ignore[method-assign]

    filter_complex = capture_merge_filter(worker, tmp_path)

    assert "[0:a]adelay=0:all=1[a0]" in filter_complex
    assert "[1:a]atempo=1.5,adelay=1000:all=1[a1]" in filter_complex
    assert "[2:a]atempo=2,atempo=2,atempo=1.125,adelay=2000:all=1[a2]" in filter_complex


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
    assert "[aoriginal][adubbed]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]" in filter_complex
    assert cmd[cmd.index("-map") + 1] == "[vout]"


def test_tempo_filter_supports_slow_output_speed() -> None:
    worker = VideoProcessingWorker()

    assert worker._build_tempo_filter(0.25) == "atempo=0.5,atempo=0.5"
