from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.services.video_splitter import VideoSplitError, probe_duration_seconds


class VideoCombineError(RuntimeError):
    """Raised when processed collection segments cannot be combined."""


@dataclass(frozen=True)
class CombinedVideo:
    path: Path
    duration_seconds: float | None = None


def combine_videos(input_paths: list[Path], output_path: Path) -> CombinedVideo:
    if not input_paths:
        raise VideoCombineError("Choose at least one processed segment to combine")

    missing_paths = [str(path) for path in input_paths if not path.is_file()]
    if missing_paths:
        raise VideoCombineError(f"Processed segment file not found: {missing_paths[0]}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run_concat(input_paths, output_path, copy_codecs=True)
    except VideoCombineError:
        _run_concat(input_paths, output_path, copy_codecs=False)

    duration: float | None = None
    try:
        duration = round(probe_duration_seconds(output_path), 3)
    except VideoSplitError:
        duration = None

    return CombinedVideo(path=output_path, duration_seconds=duration)


def _run_concat(input_paths: list[Path], output_path: Path, *, copy_codecs: bool) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as list_file:
        list_path = Path(list_file.name)
        for input_path in input_paths:
            escaped_path = str(input_path.resolve()).replace("'", "'\\''")
            list_file.write(f"file '{escaped_path}'\n")

    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
        ]
        if copy_codecs:
            cmd.extend(["-c", "copy"])
        else:
            cmd.extend(["-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart"])
        cmd.append(str(output_path))

        process = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if process.returncode != 0:
            details = process.stderr.strip() or process.stdout.strip()
            mode = "copy" if copy_codecs else "re-encode"
            raise VideoCombineError(f"video combine failed during {mode}: {details}")
    finally:
        list_path.unlink(missing_ok=True)
