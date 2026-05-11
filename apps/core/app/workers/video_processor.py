from __future__ import annotations

import html
import json
import logging
import os
import queue
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select
from faster_whisper import WhisperModel

from app.api.job_updates import job_update_broker
from app.db.database import engine
from app.models.entities import (
    Artifact,
    Job,
    JobStatus,
    ProviderRequest,
    ProviderRequestStatus,
)
from app.utils import run_cmd
from app.providers.dub_provider import DubProviderClient, TtsChunkRequest

PROCESSED_ARTIFACT_TYPE = "dubbed_video"
SRT_ARTIFACT_TYPE = "subtitle_srt"
TTS_AUDIO_ARTIFACT_TYPE = "tts_audio"
SOURCE_VIDEO_ARTIFACT_TYPE = "source_video"

WORK_DIR = Path("uploads/work")
PROCESSED_OUTPUT_DIR = Path("uploads/processed_videos")
logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    """Raised when a pipeline step fails with a user-visible error."""


class VideoProcessingWorker:
    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[int, str | None]] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="video-processing-worker", daemon=True
        )
        self._dub_provider = DubProviderClient()

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put((-1, None))
        self._thread.join(timeout=5)

    def enqueue(self, job_id: int, retry_from_step: str | None = None) -> None:
        self._queue.put((job_id, retry_from_step))

    def _run(self) -> None:
        while not self._stop_event.is_set():
            job_id, retry_from_step = self._queue.get()
            if job_id == -1:
                self._queue.task_done()
                continue
            try:
                self._process_job(job_id, retry_from_step=retry_from_step)
            finally:
                self._queue.task_done()

    def _process_job(self, job_id: int, retry_from_step: str | None = None) -> None:
        try:
            self._process_job_impl(job_id, retry_from_step=retry_from_step)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Video processing failed for job_id=%s", job_id)
            self._mark_job_failed(job_id, "pipeline_error", str(exc))

    def _process_job_impl(
        self, job_id: int, retry_from_step: str | None = None
    ) -> None:
        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job or job.status not in (JobStatus.UPLOADED, JobStatus.PROCESSING):
                return
            target_language = job.target_language
            translation_context = job.translation_context
            voice_id = job.voice_id
            output_video_speed = job.output_video_speed
            original_audio_volume = job.original_audio_volume

            source_artifact = session.exec(
                select(Artifact).where(
                    Artifact.job_id == job_id,
                    Artifact.artifact_type == SOURCE_VIDEO_ARTIFACT_TYPE,
                )
            ).first()
            if not source_artifact:
                raise PipelineError("Missing source_video artifact")

            source_video_path = Path(source_artifact.storage_url)
            if not source_video_path.exists():
                raise PipelineError("Source video file not found")

            srt_artifact_path = self._get_existing_artifact_path(
                session, job_id, SRT_ARTIFACT_TYPE
            )
            tts_audio_artifact_path = self._get_existing_artifact_path(
                session, job_id, TTS_AUDIO_ARTIFACT_TYPE
            )

        WORK_DIR.mkdir(parents=True, exist_ok=True)
        PROCESSED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        job_work_dir = WORK_DIR / f"job_{job_id}"
        job_work_dir.mkdir(parents=True, exist_ok=True)

        source_audio_path = job_work_dir / "source.wav"
        srt_source_path = job_work_dir / "source.srt"
        translated_srt_path = job_work_dir / "translated.srt"
        tts_audio_path = job_work_dir / "dubbed.wav"
        reusable_translated_srt_path = srt_artifact_path or translated_srt_path
        reusable_tts_audio_path = tts_audio_artifact_path or tts_audio_path

        can_reuse_translated_srt = (
            self._can_retry_after_step(retry_from_step, "synthesizing_chunks")
            and reusable_translated_srt_path.exists()
        )

        if can_reuse_translated_srt:
            translated_srt_path = reusable_translated_srt_path
            translated_srt_text = translated_srt_path.read_text(encoding="utf-8")
            logger.info(
                "Reusing translated SRT for job_id=%s while retrying from step=%s",
                job_id,
                retry_from_step,
            )
        else:
            if self._can_retry_after_step(retry_from_step, "transcribing"):
                if source_audio_path.exists():
                    logger.info(
                        "Reusing extracted audio for job_id=%s while retrying from step=%s",
                        job_id,
                        retry_from_step,
                    )
                else:
                    self._update_job(job_id, "extracting_audio", 10)
                    self._extract_audio(source_video_path, source_audio_path)
            else:
                self._update_job(job_id, "extracting_audio", 10)
                self._extract_audio(source_video_path, source_audio_path)

            if (
                self._can_retry_after_step(retry_from_step, "translating")
                and srt_source_path.exists()
            ):
                srt_source_text = srt_source_path.read_text(encoding="utf-8")
                logger.info(
                    "Reusing source SRT for job_id=%s while retrying from step=%s",
                    job_id,
                    retry_from_step,
                )
            else:
                self._update_job(job_id, "transcribing", 30)
                srt_source_text = self._transcribe_to_srt(source_audio_path)
                srt_source_path.write_text(srt_source_text, encoding="utf-8")

            self._update_job(job_id, "translating", 45)
            translated_srt_text = self._translate_srt(
                srt_source_text, target_language, translation_context
            )
            translated_srt_path.write_text(translated_srt_text, encoding="utf-8")

        provider_request_ids: list[str] = []
        if (
            self._can_retry_after_step(retry_from_step, "muxing")
            and reusable_tts_audio_path.exists()
        ):
            tts_audio_path = reusable_tts_audio_path
            logger.info(
                "Reusing synthesized TTS audio for job_id=%s while retrying from step=%s",
                job_id,
                retry_from_step,
            )
        else:
            self._update_job(
                job_id,
                "synthesizing_chunks",
                65,
                status=JobStatus.WAITING_PROVIDER,
            )
            tts_audio_path, provider_request_ids = self._synthesize_dubbed_audio_from_srt(
                job_id,
                translated_srt_text,
                job_work_dir,
                voice_id,
            )

        with Session(engine) as session:
            for provider_request_id in provider_request_ids:
                self._upsert_provider_request(session, job_id, provider_request_id)
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return
            self._update_job_progress(
                session, job, "muxing", 85, status=JobStatus.FINALIZING
            )

        output_path = PROCESSED_OUTPUT_DIR / f"job_{job_id}_dubbed.mp4"
        self._mux_audio(
            source_video_path,
            tts_audio_path,
            translated_srt_path,
            output_path,
            output_video_speed=output_video_speed,
            original_audio_volume=original_audio_volume,
        )

        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return

            self._upsert_artifact(
                session, job_id, PROCESSED_ARTIFACT_TYPE, output_path, "video/mp4"
            )
            self._upsert_artifact(
                session,
                job_id,
                SRT_ARTIFACT_TYPE,
                translated_srt_path,
                "application/x-subrip",
            )
            self._upsert_artifact(
                session, job_id, TTS_AUDIO_ARTIFACT_TYPE, tts_audio_path, "audio/wav"
            )

            job.status = JobStatus.COMPLETED
            job.current_step = "done"
            job.progress_percent = 100
            job.updated_at = datetime.now(timezone.utc)
            job.error_code = None
            job.error_message = None
            session.add(job)
            session.commit()
            job_update_broker.notify(job.id, "job_completed")

    def _can_retry_after_step(self, retry_from_step: str | None, step: str) -> bool:
        if retry_from_step is None:
            return False

        step_order = {
            "extracting_audio": 0,
            "transcribing": 1,
            "translating": 2,
            "synthesizing_chunks": 3,
            "muxing": 4,
        }
        retry_step_index = step_order.get(retry_from_step)
        step_index = step_order.get(step)
        return (
            retry_step_index is not None
            and step_index is not None
            and retry_step_index >= step_index
        )

    def _get_existing_artifact_path(
        self, session: Session, job_id: int, artifact_type: str
    ) -> Path | None:
        artifact = session.exec(
            select(Artifact).where(
                Artifact.job_id == job_id, Artifact.artifact_type == artifact_type
            )
        ).first()
        if not artifact:
            return None

        path = Path(artifact.storage_url)
        return path if path.exists() else None

    def _update_job(
        self,
        job_id: int,
        step: str,
        progress: int,
        *,
        status: JobStatus = JobStatus.PROCESSING,
    ) -> None:
        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return
            self._update_job_progress(session, job, step, progress, status=status)

    def _extract_audio(self, source_video: Path, output_audio: Path) -> None:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_audio),
        ]
        self._run_cmd(cmd, "audio extraction failed")

    def _transcribe_to_srt(self, source_audio: Path) -> str:
        model_name = os.getenv("WHISPER_MODEL", "small")
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        model = WhisperModel(model_name, compute_type=compute_type)
        segments, _ = model.transcribe(str(source_audio), vad_filter=True)
        srt_blocks: list[str] = []
        for idx, segment in enumerate(segments, start=1):
            text = segment.text.strip()
            if not text:
                continue
            start_ts = self._seconds_to_srt_time(segment.start)
            end_ts = self._seconds_to_srt_time(segment.end)
            srt_blocks.append(f"{idx}\n{start_ts} --> {end_ts}\n{text}")

        if not srt_blocks:
            raise PipelineError("Whisper returned no transcription segments")
        return "\n\n".join(srt_blocks) + "\n"

    def _translate_srt(
        self,
        srt_text: str,
        target_language: str,
        translation_context: str | None = None,
    ) -> str:
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            return srt_text

        model = os.getenv("OPENAI_TRANSLATION_MODEL", "gpt-4.1-mini")

        blocks = self._parse_srt_blocks(srt_text)
        if not blocks:
            return srt_text

        translated_texts = self._translate_cues_with_openai(
            openai_api_key=openai_api_key,
            model=model,
            target_language=target_language,
            translation_context=translation_context,
            cues=self._build_translation_cues(blocks),
        )

        rebuilt_blocks = []
        for idx, (sequence, timing, _original_text) in enumerate(blocks):
            translated_line = translated_texts[idx].strip()
            rebuilt_blocks.append(f"{sequence}\n{timing}\n{translated_line}")

        return "\n\n".join(rebuilt_blocks) + "\n"

    def _parse_srt_blocks(self, srt_text: str) -> list[tuple[str, str, str]]:
        blocks: list[tuple[str, str, str]] = []
        for raw_block in re.split(r"\n\s*\n", srt_text.strip()):
            lines = [line.rstrip() for line in raw_block.splitlines() if line.strip()]
            if len(lines) < 3:
                continue
            if "-->" not in lines[1]:
                continue
            sequence = lines[0]
            timing = lines[1]
            text = " ".join(lines[2:]).strip()
            if not text:
                continue
            blocks.append((sequence, timing, text))
        return blocks

    def _build_translation_cues(
        self, blocks: list[tuple[str, str, str]]
    ) -> list[dict[str, object]]:
        cues: list[dict[str, object]] = []
        timing_ranges = [
            self._parse_srt_timing_range(timing) for _sequence, timing, _text in blocks
        ]
        for index, (_sequence, timing, text) in enumerate(blocks):
            start_time, end_time = timing_ranges[index]
            duration_seconds = max(0.0, end_time - start_time)
            break_after_seconds = 0.0
            if index + 1 < len(timing_ranges):
                next_start_time, _next_end_time = timing_ranges[index + 1]
                break_after_seconds = max(0.0, next_start_time - end_time)
            cues.append(
                {
                    "index": index,
                    "timing": timing,
                    "duration_seconds": round(duration_seconds, 3),
                    "break_after_seconds": round(break_after_seconds, 3),
                    "text": text,
                }
            )
        return cues

    def _translate_cues_with_openai(
        self,
        *,
        openai_api_key: str,
        model: str,
        target_language: str,
        translation_context: str | None = None,
        cues: list[dict[str, object]],
    ) -> list[str]:
        context_instruction = ""
        if translation_context:
            context_instruction = (
                "\n### User Context\n"
                f"Use this additional context when choosing wording, tone, and names: {translation_context}\n"
            )

        system_text = (
            "### Persona & Goal\n"
            "You are a professional Subtitle Translator and Dubbing Script Editor. "
            f"Your goal is to translate SRT cues into {target_language} while ensuring isochrony: the spoken duration of each translation must fit the original timing provided in `duration_seconds`.\n\n"
            "### Task Instructions\n"
            f"Translate the `text` field of each provided JSON object into {target_language}. Read the entire ordered cue list as one continuous dubbing script so you can maintain sentence flow, tone, and natural punctuation across cue boundaries. Use `break_after_seconds` to understand how much silence follows a cue. Add reasonable commas or periods where the full translated script needs natural pauses, and treat any break greater than 0.3 seconds as an SSML pause that will be compiled as `<break time={{seconds:.2f}}s/>` during synthesis.\n"
            f"{context_instruction}\n"
            "### Strict Rules (Priority Order):\n"
            '1. **Output Format:** Return ONLY a raw JSON array of strings (e.g., ["Translated text 1", "Translated text 2"]). Do not use markdown code blocks, introductory text, concluding text, or extra JSON keys.\n'
            '2. **The "Dubbing" Constraint (Timing is King):**\n'
            "   - **Hard Constraint:** Each translation must be speakable at a natural, conversational pace within its `duration_seconds`.\n"
            "   - **Priority:** Timing and brevity > literal accuracy.\n"
            "   - If a literal translation is too long, use shorter synonyms, compress phrasing, or omit non-essential filler words. The line must fit without forcing the voice actor to speak unnaturally fast.\n"
            "3. **1:1 Mapping:** The output array must contain exactly the same number of elements as the input array. Do not merge, skip, or split cues.\n"
            "4. **Sentence Continuity:** If a sentence spans multiple cues, ensure grammatical flow and tone are maintained across the breaks while respecting the duration of each individual fragment.\n"
            "5. **SSML Break Awareness:** Do not include SSML tags in the JSON strings. Use `break_after_seconds` only to choose punctuation; the application will insert `<break time=.../>` tags for pauses greater than 0.3 seconds when compiling SSML.\n"
            "6. **Non-Speech Elements:** Preserve all tags in brackets (e.g., [music], [laughter]) or speaker identifiers (e.g., MAN:) exactly as they appear.\n"
            f"7. **Naturalness:** Use idiomatic, spoken-style {target_language}. Ensure pronouns and levels of formality are consistent throughout the batch.\n"
            f"8. **Fallback:** If a cue is already in {target_language} or contains no translatable text, copy the original string verbatim."
        )

        payload = {
            "model": model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": system_text,
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(cues, ensure_ascii=False),
                        }
                    ],
                },
            ],
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {openai_api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise PipelineError(f"OpenAI translation request failed: {exc}") from exc

        translated_raw = self._extract_openai_output_text(response_data)
        if not translated_raw:
            raise PipelineError("OpenAI translation returned empty output_text")

        translated = self._parse_openai_translations(
            translated_raw, expected_count=len(cues)
        )
        if translated is None:
            raise PipelineError("OpenAI translation output was not valid JSON")

        normalized = [str(item).strip() for item in translated]
        if any(not item for item in normalized):
            raise PipelineError("OpenAI translation produced empty subtitle lines")
        return normalized

    def _parse_openai_translations(
        self, translated_raw: str, expected_count: int
    ) -> list[str] | None:
        parsed = self._json_load_list(translated_raw)
        if parsed is None:
            parsed = self._json_load_list(
                self._strip_markdown_code_fences(translated_raw)
            )

        if parsed is None:
            return None

        if len(parsed) == expected_count:
            return parsed

        if expected_count == 1:
            return [
                "\n".join(str(item).strip() for item in parsed if str(item).strip())
            ]

        return None

    def _json_load_list(self, raw: str) -> list[str] | None:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return None

        if not isinstance(loaded, list):
            return None

        return [str(item) for item in loaded]

    def _strip_markdown_code_fences(self, value: str) -> str:
        stripped = value.strip()
        if not stripped.startswith("```"):
            return stripped

        lines = stripped.splitlines()
        if len(lines) < 3:
            return stripped

        first_line = lines[0].strip()
        last_line = lines[-1].strip()
        if not last_line.startswith("```"):
            return stripped

        if first_line in {"```", "```json", "```JSON"}:
            return "\n".join(lines[1:-1]).strip()

        return stripped

    def _extract_openai_output_text(self, response_data: dict) -> str:
        output_text = response_data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output_items = response_data.get("output")
        if not isinstance(output_items, list):
            return ""

        text_chunks: list[str] = []
        for item in output_items:
            if not isinstance(item, dict):
                continue
            for content_item in item.get("content", []):
                if not isinstance(content_item, dict):
                    continue
                raw_text = content_item.get("text")
                if isinstance(raw_text, str):
                    stripped = raw_text.strip()
                    if stripped:
                        text_chunks.append(stripped)
                    continue
                if isinstance(raw_text, list):
                    for line in raw_text:
                        if isinstance(line, str):
                            stripped = line.strip()
                            if stripped:
                                text_chunks.append(stripped)

        return "\n".join(text_chunks).strip()

    def _parse_srt_timing_range(self, timing: str) -> tuple[float, float]:
        start_raw, end_raw = [part.strip() for part in timing.split("-->", maxsplit=1)]
        return self._parse_srt_time(start_raw), self._parse_srt_time(end_raw)

    def _parse_srt_time(self, value: str) -> float:
        hours_raw, minutes_raw, seconds_raw = value.split(":", maxsplit=2)
        seconds_part, millis_part = seconds_raw.split(",", maxsplit=1)
        total_seconds = (
            int(hours_raw) * 3600
            + int(minutes_raw) * 60
            + int(seconds_part)
            + int(millis_part) / 1000.0
        )
        return total_seconds

    def _synthesize_dubbed_audio_from_srt(
        self,
        job_id: int,
        translated_srt: str,
        job_work_dir: Path,
        voice_id: str | None = None,
    ) -> tuple[Path, list[str]]:
        blocks = self._parse_srt_blocks(translated_srt)
        if not blocks:
            raise PipelineError(
                "Translated SRT has no usable subtitle blocks for SSML synthesis"
            )

        output_audio = job_work_dir / "dubbed.wav"
        ssml_text, duration_seconds = self._compile_ssml_from_srt_blocks(blocks)
        chunk_requests = [
            TtsChunkRequest(
                chunk_index=1,
                text=ssml_text,
                output_audio=output_audio,
                duration_seconds=duration_seconds,
                voice_id=voice_id,
            )
        ]
        provider_request_ids = self._dub_provider.synthesize_chunks(
            job_id, chunk_requests
        )
        return output_audio, provider_request_ids

    def _compile_ssml_from_srt_blocks(
        self, blocks: list[tuple[str, str, str]]
    ) -> tuple[str, float]:
        ssml_parts: list[str] = []
        first_start_time: float | None = None
        previous_end_time: float | None = None
        last_end_time = 0.0

        for _sequence, timing, text in blocks:
            start_time, end_time = self._parse_srt_timing_range(timing)
            if end_time < start_time:
                raise PipelineError(f"Invalid SRT timing range: {timing}")
            if first_start_time is None:
                first_start_time = start_time
            if previous_end_time is not None:
                break_seconds = max(0.0, start_time - previous_end_time)
                if break_seconds > 0.3:
                    ssml_parts.append(f"<break time={break_seconds:.2f}s/>")

            normalized_text = " ".join(text.split())
            if normalized_text:
                ssml_parts.append(html.escape(normalized_text, quote=False))

            previous_end_time = end_time
            last_end_time = max(last_end_time, end_time)

        if first_start_time is None:
            raise PipelineError("Translated SRT has no usable subtitle blocks for SSML synthesis")

        duration_seconds = max(0.1, last_end_time - first_start_time)
        return " ".join(ssml_parts), duration_seconds

    def _split_atempo_factors(self, speedup: float) -> list[float]:
        if speedup <= 0:
            raise PipelineError("audio tempo speed must be positive")

        factors: list[float] = []
        remaining_speedup = speedup
        while remaining_speedup > 2.0:
            factors.append(2.0)
            remaining_speedup /= 2.0
        while remaining_speedup < 0.5:
            factors.append(0.5)
            remaining_speedup /= 0.5
        if abs(remaining_speedup - 1.0) > 0.000001:
            factors.append(remaining_speedup)
        return factors

    def _mux_audio(
        self,
        source_video: Path,
        dubbed_audio: Path,
        subtitles: Path,
        output_video: Path,
        *,
        output_video_speed: float = 1.0,
        original_audio_volume: float = 0.15,
    ) -> None:
        if output_video_speed <= 0:
            raise PipelineError("output_video_speed must be positive")
        if original_audio_volume < 0:
            raise PipelineError("original_audio_volume must be non-negative")

        subtitle_style = "FontSize=12,PrimaryColour=&H00000000,BackColour=&H00FFFFFF,BorderStyle=4,Outline=0,Shadow=0,Alignment=2,MarginV=50"
        subtitle_filter = (
            f"subtitles=filename={self._escape_ffmpeg_filter_path(subtitles)}"
            f":charenc=UTF-8:force_style={self._escape_ffmpeg_filter_value(subtitle_style)}"
        )
        tempo_filter = self._build_tempo_filter(output_video_speed)
        filter_complex = ";".join(
            [
                f"[0:v]{subtitle_filter},setpts=PTS/{output_video_speed:.6g}[vout]",
                f"[0:a]volume={original_audio_volume:.6g},{tempo_filter}[aoriginal]",
                f"[1:a]{tempo_filter}[adubbed]",
                "[aoriginal][adubbed]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]",
            ]
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-i",
            str(dubbed_audio),
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output_video),
        ]
        self._run_cmd(cmd, "audio/video/subtitle burn-in failed")

    def _build_tempo_filter(self, speed: float) -> str:
        if abs(speed - 1.0) <= 0.000001:
            return "anull"
        return ",".join(
            f"atempo={factor:.6g}" for factor in self._split_atempo_factors(speed)
        )

    def _escape_ffmpeg_filter_path(self, path: Path) -> str:
        return (
            "'"
            + str(path).replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
            + "'"
        )

    def _escape_ffmpeg_filter_value(self, value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    def _run_cmd(self, cmd: list[str], error_message: str) -> None:
        run_cmd(cmd, error_message, PipelineError)

    def _upsert_provider_request(
        self, session: Session, job_id: int, provider_request_id: str
    ) -> None:
        provider_request = session.exec(
            select(ProviderRequest).where(
                ProviderRequest.provider_request_id == provider_request_id
            )
        ).first()
        if provider_request:
            provider_request.status = ProviderRequestStatus.SUCCEEDED
            provider_request.callback_received = True
            provider_request.updated_at = datetime.now(timezone.utc)
        else:
            provider_request = ProviderRequest(
                job_id=job_id,
                provider_name="dub_provider",
                provider_request_id=provider_request_id,
                status=ProviderRequestStatus.SUCCEEDED,
                callback_received=True,
            )
            session.add(provider_request)
        session.commit()
        job_update_broker.notify(job_id, "provider_request_updated")

    def _upsert_artifact(
        self,
        session: Session,
        job_id: int,
        artifact_type: str,
        path: Path,
        content_type: str,
    ) -> None:
        artifact = session.exec(
            select(Artifact).where(
                Artifact.job_id == job_id, Artifact.artifact_type == artifact_type
            )
        ).first()
        if artifact:
            artifact.storage_url = str(path)
            artifact.content_type = content_type
        else:
            session.add(
                Artifact(
                    job_id=job_id,
                    artifact_type=artifact_type,
                    storage_url=str(path),
                    content_type=content_type,
                )
            )

    def _update_job_progress(
        self,
        session: Session,
        job: Job,
        step: str,
        progress: int,
        *,
        status: JobStatus = JobStatus.PROCESSING,
    ) -> None:
        job.status = status
        job.current_step = step
        job.progress_percent = max(job.progress_percent, progress)
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        job_update_broker.notify(job.id, "job_progress_updated")

    def _mark_job_failed(
        self, job_id: int, error_code: str, error_message: str
    ) -> None:
        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return
            job.status = JobStatus.FAILED
            job.error_code = error_code
            job.error_message = error_message[:1024]
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()
            job_update_broker.notify(job.id, "job_failed")

    def _seconds_to_srt_time(self, seconds: float) -> str:
        safe_seconds = max(0.0, float(seconds))
        millis_total = int(round(safe_seconds * 1000))
        hours, remainder = divmod(millis_total, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, millis = divmod(remainder, 1_000)
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


video_processing_worker = VideoProcessingWorker()
