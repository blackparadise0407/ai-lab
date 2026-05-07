from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path


class VideoSplitError(RuntimeError):
    """Raised when source video probing or splitting fails."""


@dataclass(frozen=True)
class SplitSegment:
    sequence_index: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    path: Path


def probe_duration_seconds(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    process = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        details = process.stderr.strip() or process.stdout.strip()
        raise VideoSplitError(f"video duration probe failed: {details}")

    try:
        duration_seconds = float(json.loads(process.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise VideoSplitError(f"video duration probe returned invalid output for {path}") from exc

    if duration_seconds <= 0:
        raise VideoSplitError(f"video duration probe returned non-positive duration for {path}")
    return duration_seconds


def split_video(path: Path, output_dir: Path, max_segment_seconds: int = 60) -> list[SplitSegment]:
    if max_segment_seconds <= 0:
        raise VideoSplitError("max_segment_seconds must be positive")

    duration_seconds = probe_duration_seconds(path)
    output_dir.mkdir(parents=True, exist_ok=True)

    if duration_seconds <= max_segment_seconds:
        return [
            SplitSegment(
                sequence_index=1,
                start_seconds=0.0,
                end_seconds=round(duration_seconds, 3),
                duration_seconds=round(duration_seconds, 3),
                path=path,
            )
        ]

    segment_count = math.ceil(duration_seconds / max_segment_seconds)
    extension = path.suffix or ".mp4"
    segments: list[SplitSegment] = []

    for index in range(segment_count):
        start_seconds = float(index * max_segment_seconds)
        end_seconds = min(duration_seconds, float((index + 1) * max_segment_seconds))
        segment_duration = max(0.0, end_seconds - start_seconds)
        segment_path = output_dir / f"segment_{index + 1:03d}{extension}"
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start_seconds:.3f}",
            "-i",
            str(path),
            "-t",
            f"{segment_duration:.3f}",
            "-map",
            "0",
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(segment_path),
        ]
        process = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if process.returncode != 0:
            details = process.stderr.strip() or process.stdout.strip()
            raise VideoSplitError(f"video split failed for segment {index + 1}: {details}")

        segments.append(
            SplitSegment(
                sequence_index=index + 1,
                start_seconds=round(start_seconds, 3),
                end_seconds=round(end_seconds, 3),
                duration_seconds=round(segment_duration, 3),
                path=segment_path,
            )
        )

    return segments
