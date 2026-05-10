from __future__ import annotations

from pathlib import Path

from app.workers.video_processor import VideoProcessingWorker


def capture_merge_command(worker: VideoProcessingWorker, tmp_path: Path) -> list[str]:
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

    return captured["cmd"]


def test_merge_tts_chunks_concatenates_sequentially_with_sentence_breaks(
    tmp_path,
) -> None:
    worker = VideoProcessingWorker()

    cmd = capture_merge_command(worker, tmp_path)
    filter_complex = cmd[cmd.index("-filter_complex") + 1]

    assert "-t" in cmd
    assert cmd[cmd.index("-t") + 1] == "0.300"
    assert "anullsrc=r=48000:cl=stereo" in cmd
    assert "asplit=3[s0][s1][s2]" in filter_complex
    assert "[a0][s0][a1][s1][a2][s2]concat=n=6:v=0:a=1" in filter_complex


def test_merge_tts_chunks_does_not_speed_up_long_chunks(tmp_path) -> None:
    worker = VideoProcessingWorker()

    cmd = capture_merge_command(worker, tmp_path)
    filter_complex = cmd[cmd.index("-filter_complex") + 1]

    assert "atempo" not in filter_complex
    assert "adelay" not in filter_complex
    assert "amix" not in filter_complex


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
