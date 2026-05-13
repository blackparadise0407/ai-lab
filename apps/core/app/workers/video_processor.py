from __future__ import annotations

import html
import json
import logging
import os
import queue
import subprocess
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
ASS_ARTIFACT_TYPE = "subtitle_ass"
TTS_AUDIO_ARTIFACT_TYPE = "tts_audio"
SOURCE_VIDEO_ARTIFACT_TYPE = "source_video"
SOURCE_TRANSCRIPT_ARTIFACT_TYPE = "source_transcript"
TARGET_SCRIPT_ARTIFACT_TYPE = "target_script"
DUBBED_TRANSCRIPT_ARTIFACT_TYPE = "dubbed_transcript"

WORK_DIR = Path("uploads/work")
PROCESSED_OUTPUT_DIR = Path("uploads/processed_videos")
logger = logging.getLogger(__name__)

WHISPER_LANGUAGE_ALIASES = {
    "cmn": "zh",
    "fil": "tl",
    "nb": "no",
}


class PipelineError(RuntimeError):
    """Raised when a pipeline step fails with a user-visible error."""


class JobCanceled(RuntimeError):
    """Raised when a job cancellation should stop pipeline execution."""


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
        except JobCanceled:
            logger.info("Video processing canceled for job_id=%s", job_id)
            self._mark_job_canceled(job_id)
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

            tts_audio_artifact_path = self._get_existing_artifact_path(
                session, job_id, TTS_AUDIO_ARTIFACT_TYPE
            )

        WORK_DIR.mkdir(parents=True, exist_ok=True)
        PROCESSED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        job_work_dir = WORK_DIR / f"job_{job_id}"
        job_work_dir.mkdir(parents=True, exist_ok=True)

        source_audio_path = job_work_dir / "source.wav"
        srt_source_path = job_work_dir / "source.srt"
        source_transcript_path = job_work_dir / "source_transcript.json"
        target_script_path = job_work_dir / "target_script.json"
        dubbed_transcript_path = job_work_dir / "dubbed_transcript.json"
        ass_subtitle_path = job_work_dir / "karaoke.ass"
        tts_audio_path = job_work_dir / "dubbed.wav"
        reusable_tts_audio_path = tts_audio_artifact_path or tts_audio_path

        if (
            self._can_retry_after_step(retry_from_step, "transcribing_source")
            and source_audio_path.exists()
        ):
            logger.info(
                "Reusing extracted audio for job_id=%s while retrying from step=%s",
                job_id,
                retry_from_step,
            )
        else:
            self._update_job(job_id, "extracting_audio", 10)
            self._extract_audio(source_video_path, source_audio_path, job_id=job_id)
            self._raise_if_canceled(job_id)

        if (
            self._can_retry_after_step(retry_from_step, "building_target_script")
            and source_transcript_path.exists()
        ):
            source_transcript = self._read_json_file(source_transcript_path)
            logger.info(
                "Reusing source transcript for job_id=%s while retrying from step=%s",
                job_id,
                retry_from_step,
            )
        else:
            self._update_job(job_id, "transcribing_source", 25)
            self._raise_if_canceled(job_id)
            source_transcript = self._transcribe_audio(
                source_audio_path, language=job.source_language, word_timestamps=False
            )
            self._raise_if_canceled(job_id)
            source_transcript_path.write_text(
                json.dumps(source_transcript, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            srt_source_path.write_text(
                self._transcript_to_srt(source_transcript), encoding="utf-8"
            )

        if (
            self._can_retry_after_step(retry_from_step, "synthesizing_dub")
            and target_script_path.exists()
        ):
            target_script = self._read_json_file(target_script_path)
            logger.info(
                "Reusing target script for job_id=%s while retrying from step=%s",
                job_id,
                retry_from_step,
            )
        else:
            self._update_job(job_id, "building_target_script", 45)
            self._raise_if_canceled(job_id)
            target_script = self._build_target_dubbing_script(
                source_transcript, target_language, translation_context
            )
            self._raise_if_canceled(job_id)
            target_script_path.write_text(
                json.dumps(target_script, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        provider_request_ids: list[str] = []
        if (
            self._can_retry_after_step(retry_from_step, "transcribing_dub")
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
                "synthesizing_dub",
                60,
                status=JobStatus.WAITING_PROVIDER,
            )
            self._raise_if_canceled(job_id)
            tts_audio_path, provider_request_ids = (
                self._synthesize_dubbed_audio_from_script(
                    job_id,
                    target_script,
                    job_work_dir,
                    voice_id,
                )
            )
            self._raise_if_canceled(job_id)

        if (
            self._can_retry_after_step(retry_from_step, "generating_ass")
            and dubbed_transcript_path.exists()
        ):
            dubbed_transcript = self._read_json_file(dubbed_transcript_path)
            logger.info(
                "Reusing dubbed transcript for job_id=%s while retrying from step=%s",
                job_id,
                retry_from_step,
            )
        else:
            self._update_job(job_id, "transcribing_dub", 75)
            self._raise_if_canceled(job_id)
            dubbed_transcript = self._transcribe_audio(
                tts_audio_path, language=target_language, word_timestamps=True
            )
            self._raise_if_canceled(job_id)
            dubbed_transcript_path.write_text(
                json.dumps(dubbed_transcript, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if (
            self._can_retry_after_step(retry_from_step, "muxing")
            and ass_subtitle_path.exists()
        ):
            logger.info(
                "Reusing ASS subtitles for job_id=%s while retrying from step=%s",
                job_id,
                retry_from_step,
            )
        else:
            self._update_job(job_id, "generating_ass", 82)
            self._raise_if_canceled(job_id)
            ass_subtitle_path.write_text(
                self._generate_karaoke_ass(dubbed_transcript), encoding="utf-8"
            )

        with Session(engine) as session:
            for provider_request_id in provider_request_ids:
                self._upsert_provider_request(session, job_id, provider_request_id)
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return
            self._update_job_progress(
                session, job, "muxing", 90, status=JobStatus.FINALIZING
            )

        self._raise_if_canceled(job_id)
        output_path = PROCESSED_OUTPUT_DIR / f"job_{job_id}_dubbed.mp4"
        self._mux_audio(
            source_video_path,
            tts_audio_path,
            ass_subtitle_path,
            output_path,
            output_video_speed=output_video_speed,
            original_audio_volume=original_audio_volume,
            job_id=job_id,
        )
        self._raise_if_canceled(job_id)

        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return
            if job.status == JobStatus.CANCELED:
                raise JobCanceled()

            self._upsert_artifact(
                session, job_id, PROCESSED_ARTIFACT_TYPE, output_path, "video/mp4"
            )
            self._upsert_artifact(
                session,
                job_id,
                SOURCE_TRANSCRIPT_ARTIFACT_TYPE,
                source_transcript_path,
                "application/json",
            )
            self._upsert_artifact(
                session,
                job_id,
                TARGET_SCRIPT_ARTIFACT_TYPE,
                target_script_path,
                "application/json",
            )
            self._upsert_artifact(
                session,
                job_id,
                DUBBED_TRANSCRIPT_ARTIFACT_TYPE,
                dubbed_transcript_path,
                "application/json",
            )
            self._upsert_artifact(
                session, job_id, ASS_ARTIFACT_TYPE, ass_subtitle_path, "text/x-ass"
            )
            self._upsert_artifact(
                session,
                job_id,
                SRT_ARTIFACT_TYPE,
                srt_source_path,
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
            "transcribing_source": 1,
            "translating": 2,
            "building_target_script": 2,
            "synthesizing_chunks": 3,
            "synthesizing_dub": 3,
            "transcribing_dub": 4,
            "generating_ass": 5,
            "muxing": 6,
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

    def _extract_audio(
        self, source_video: Path, output_audio: Path, *, job_id: int | None = None
    ) -> None:
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
        self._run_cmd(cmd, "audio extraction failed", job_id=job_id)

    def _read_json_file(self, path: Path) -> dict[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PipelineError(f"Invalid JSON artifact: {path}") from exc
        if not isinstance(value, dict):
            raise PipelineError(f"JSON artifact must be an object: {path}")
        return value

    @staticmethod
    def _normalize_whisper_language_code(language: str | None) -> str:
        normalized_language = (language or "").strip().replace("_", "-")
        if not normalized_language:
            return ""

        primary_subtag = normalized_language.split("-", 1)[0].lower()
        return WHISPER_LANGUAGE_ALIASES.get(primary_subtag, primary_subtag)

    def _transcribe_audio(
        self,
        source_audio: Path,
        *,
        language: str | None = None,
        word_timestamps: bool = False,
    ) -> dict[str, object]:
        model_name = os.getenv("WHISPER_MODEL", "small")
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        model = WhisperModel(model_name, compute_type=compute_type)
        transcribe_kwargs: dict[str, object] = {
            "vad_filter": True,
            "word_timestamps": word_timestamps,
        }
        normalized_language = self._normalize_whisper_language_code(language)
        if normalized_language:
            transcribe_kwargs["language"] = normalized_language

        segments, info = model.transcribe(str(source_audio), **transcribe_kwargs)
        transcript_segments: list[dict[str, object]] = []
        for idx, segment in enumerate(segments):
            text = segment.text.strip()
            if not text:
                continue
            transcript_segment: dict[str, object] = {
                "index": idx,
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": text,
            }
            words = []
            for word in getattr(segment, "words", None) or []:
                word_text = getattr(word, "word", "").strip()
                if not word_text:
                    continue
                words.append(
                    {
                        "start": round(float(getattr(word, "start", segment.start)), 3),
                        "end": round(float(getattr(word, "end", segment.end)), 3),
                        "text": word_text,
                    }
                )
            if words:
                transcript_segment["words"] = words
            transcript_segments.append(transcript_segment)

        if not transcript_segments:
            raise PipelineError("Whisper returned no transcription segments")

        detected_language = (
            getattr(info, "language", None) or normalized_language or None
        )
        return {
            "language": detected_language,
            "duration": getattr(info, "duration", None),
            "segments": transcript_segments,
        }

    def _transcript_to_srt(self, transcript: dict[str, object]) -> str:
        blocks: list[str] = []
        segments = transcript.get("segments")
        if not isinstance(segments, list):
            return ""
        for idx, raw_segment in enumerate(segments, start=1):
            if not isinstance(raw_segment, dict):
                continue
            text = str(raw_segment.get("text") or "").strip()
            if not text:
                continue
            start = self._coerce_seconds(raw_segment.get("start"), default=0.0)
            end = self._coerce_seconds(raw_segment.get("end"), default=start + 0.1)
            blocks.append(
                f"{idx}\n{self._seconds_to_srt_time(start)} --> {self._seconds_to_srt_time(end)}\n{text}"
            )
        return "\n\n".join(blocks) + ("\n" if blocks else "")

    def _build_target_dubbing_script(
        self,
        source_transcript: dict[str, object],
        target_language: str,
        translation_context: str | None = None,
    ) -> dict[str, object]:
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            fallback_text = " ".join(
                str(segment.get("text") or "").strip()
                for segment in self._get_transcript_segments(source_transcript)
                if str(segment.get("text") or "").strip()
            )
            return {
                "target_language": target_language,
                "style_notes": "OPENAI_API_KEY is not configured; using source transcript text as a fallback script.",
                "script": fallback_text,
                "chunks": [
                    {
                        "index": segment_index,
                        "text": str(segment.get("text") or "").strip(),
                        "source_start": self._coerce_seconds(
                            segment.get("start"), default=0.0
                        ),
                        "source_end": self._coerce_seconds(
                            segment.get("end"), default=0.0
                        ),
                    }
                    for segment_index, segment in enumerate(
                        self._get_transcript_segments(source_transcript)
                    )
                    if str(segment.get("text") or "").strip()
                ],
                "glossary": [],
            }

        model = os.getenv("OPENAI_TRANSLATION_MODEL", "gpt-4.1-mini")
        return self._build_target_script_with_openai(
            openai_api_key=openai_api_key,
            model=model,
            target_language=target_language,
            translation_context=translation_context,
            source_transcript=source_transcript,
        )

    def _build_target_script_with_openai(
        self,
        *,
        openai_api_key: str,
        model: str,
        target_language: str,
        translation_context: str | None,
        source_transcript: dict[str, object],
    ) -> dict[str, object]:
        context_instruction = ""
        if translation_context:
            context_instruction = (
                "\n### User Context\n"
                "Use this context to preserve names, genre, tone, jokes, terminology, "
                f"and audience expectations: {translation_context}\n"
            )

        system_text = (
            "### Persona\n"
            "You are a professional Subtitle Translator and Dubbing Script Editor "
            "specializing in isochronous dubbing.\n\n"

            "### Task Instructions\n"
            f"Translate the `text` field of each provided JSON object into {target_language}. "
            "Read the entire ordered cue list as one continuous dubbing script so you can maintain "
            "sentence flow, tone, and natural punctuation across cue boundaries. "
            "Use `break_after_seconds` to understand how much silence follows each cue, "
            "and add appropriate commas or periods so the full script reads with natural pauses.\n\n"

            f"{context_instruction}"

            "### Strict Rules (Priority Order)\n"

            "1. **Output Format:** Return ONLY a raw JSON array of strings "
            '(e.g., ["Translated text 1", "Translated text 2"]). '
            "Do not use markdown code blocks, introductory text, concluding text, or extra JSON keys.\n\n"

            "2. **Dubbing Constraint — Timing Is King:**\n"
            "   - **Hard Constraint:** Each translation must be speakable at a natural, "
            "conversational pace within its `duration_seconds`.\n"
            "   - **Rate heuristic:** Target ~3-4 words per second. "
            "For example, a 2-second cue should contain no more than 6-8 words.\n"
            "   - **Priority:** Timing and brevity > literal accuracy.\n"
            "   - If a literal translation is too long, use shorter synonyms, compress phrasing, "
            "or omit non-essential filler words. The line must fit without forcing "
            "the voice actor to speak unnaturally fast.\n\n"

            "3. **Strict 1:1 Mapping:** The output array must contain EXACTLY the same number of "
            "elements as the input array. "
            "Merging two cues into one string is FORBIDDEN. "
            "Splitting one cue into two is FORBIDDEN. "
            "If a cue is very short or a sentence fragment, translate it as a fragment — "
            "do not combine it with adjacent cues. "
            f"If a cue is already in {target_language} or contains no translatable text, "
            "copy the original string verbatim.\n\n"

            "4. **Sentence Continuity:** When a sentence spans multiple cues, maintain grammatical "
            "and tonal flow across the breaks — but if achieving flow would violate a cue's "
            "`duration_seconds`, timing wins. It is acceptable to leave a fragment "
            "incomplete mid-sentence if the timing requires it.\n\n"

            "5. **Non-Speech Elements:** Copy all bracketed tags (e.g., [music], [laughter]) "
            "and speaker labels (e.g., MAN:) verbatim, unchanged, and in their original position "
            "within the string. Do not translate, reformat, or relocate them.\n\n"

            f"6. **Naturalness:** Use idiomatic, spoken-style {target_language}. "
            "Ensure pronouns and levels of formality are consistent throughout the batch.\n"
        )
        payload = {
            "model": model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_text}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(source_transcript, ensure_ascii=False),
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
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise PipelineError(f"OpenAI target script request failed: {exc}") from exc

        raw_output = self._extract_openai_output_text(response_data)
        parsed = self._json_load_value(raw_output)
        if parsed is None:
            parsed = self._json_load_value(
                self._strip_markdown_code_fences(raw_output)
            )
        if parsed is None:
            raise PipelineError("OpenAI target script output was not valid JSON")
        if isinstance(parsed, list):
            parsed = self._build_script_from_translation_list(
                parsed, source_transcript, target_language
            )
        return self._normalize_target_script(parsed, target_language)

    def _json_load_value(self, raw: str) -> dict[str, object] | list | None:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return loaded if isinstance(loaded, (dict, list)) else None

    def _build_script_from_translation_list(
        self,
        translations: list,
        source_transcript: dict[str, object],
        target_language: str,
    ) -> dict[str, object]:
        segments = self._get_transcript_segments(source_transcript)
        chunks: list[dict[str, object]] = []
        for idx, (translation, segment) in enumerate(zip(translations, segments)):
            text = str(translation).strip()
            if not text:
                continue
            chunks.append(
                {
                    "index": idx,
                    "text": text,
                    "source_start": self._coerce_seconds(
                        segment.get("start"), default=0.0
                    ),
                    "source_end": self._coerce_seconds(
                        segment.get("end"), default=0.0
                    ),
                }
            )
        script_text = " ".join(str(chunk["text"]) for chunk in chunks)
        return {
            "target_language": target_language,
            "style_notes": "",
            "script": script_text,
            "chunks": chunks,
            "glossary": [],
        }

    def _normalize_target_script(
        self, script_data: dict[str, object], target_language: str
    ) -> dict[str, object]:
        chunks = script_data.get("chunks")
        normalized_chunks: list[dict[str, object]] = []
        if isinstance(chunks, list):
            for idx, raw_chunk in enumerate(chunks):
                if not isinstance(raw_chunk, dict):
                    continue
                text = str(raw_chunk.get("text") or "").strip()
                if not text:
                    continue
                normalized_chunks.append(
                    {
                        "index": int(raw_chunk.get("index") or idx),
                        "text": text,
                        "source_start": self._coerce_seconds(
                            raw_chunk.get("source_start"), default=0.0
                        ),
                        "source_end": self._coerce_seconds(
                            raw_chunk.get("source_end"), default=0.0
                        ),
                    }
                )

        script_text = str(script_data.get("script") or "").strip()
        if not script_text and normalized_chunks:
            script_text = " ".join(str(chunk["text"]) for chunk in normalized_chunks)
        if not script_text:
            raise PipelineError("Target script is empty")
        if not normalized_chunks:
            normalized_chunks = [
                {
                    "index": 0,
                    "text": script_text,
                    "source_start": 0.0,
                    "source_end": max(0.1, len(script_text.split()) / 2.5),
                }
            ]

        glossary = script_data.get("glossary")
        return {
            "target_language": str(
                script_data.get("target_language") or target_language
            ),
            "style_notes": str(script_data.get("style_notes") or "").strip(),
            "script": script_text,
            "chunks": normalized_chunks,
            "glossary": glossary if isinstance(glossary, list) else [],
        }

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

    def _get_transcript_segments(
        self, transcript: dict[str, object]
    ) -> list[dict[str, object]]:
        segments = transcript.get("segments")
        if not isinstance(segments, list):
            return []
        return [segment for segment in segments if isinstance(segment, dict)]

    def _coerce_seconds(self, value: object, *, default: float) -> float:
        if isinstance(value, bool) or value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _synthesize_dubbed_audio_from_script(
        self,
        job_id: int,
        target_script: dict[str, object],
        job_work_dir: Path,
        voice_id: str | None = None,
    ) -> tuple[Path, list[str]]:
        chunks = target_script.get("chunks")
        chunk_items = (
            [chunk for chunk in chunks if isinstance(chunk, dict)]
            if isinstance(chunks, list)
            else []
        )
        if chunk_items:
            ssml_text, duration_seconds = self._compile_ssml_from_script_chunks(
                chunk_items
            )
        else:
            script_text = str(target_script.get("script") or "").strip()
            if not script_text:
                raise PipelineError("Target script has no usable text for synthesis")
            ssml_text = html.escape(" ".join(script_text.split()), quote=False)
            duration_seconds = max(0.1, len(script_text.split()) / 2.5)

        output_audio = job_work_dir / "dubbed.wav"
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

    def _compile_ssml_from_script_chunks(
        self, chunks: list[dict[str, object]]
    ) -> tuple[str, float]:
        ssml_parts: list[str] = []
        latest_source_end = 0.0
        for chunk in chunks:
            text = " ".join(str(chunk.get("text") or "").split())
            if text:
                ssml_parts.append(html.escape(text, quote=False))
            latest_source_end = max(
                latest_source_end,
                self._coerce_seconds(chunk.get("source_end"), default=0.0),
            )

        ssml_text = " ".join(ssml_parts).strip()
        if not ssml_text:
            raise PipelineError(
                "Target script chunks have no usable text for synthesis"
            )
        estimated_duration = sum(
            max(
                0.0,
                self._coerce_seconds(chunk.get("source_end"), default=0.0)
                - self._coerce_seconds(chunk.get("source_start"), default=0.0),
            )
            for chunk in chunks
        )
        word_duration = len(ssml_text.split()) / 2.5
        return ssml_text, max(0.1, latest_source_end, estimated_duration, word_duration)

    def _generate_karaoke_ass(self, transcript: dict[str, object]) -> str:
        events: list[str] = []
        for segment in self._get_transcript_segments(transcript):
            start = self._coerce_seconds(segment.get("start"), default=0.0)
            end = self._coerce_seconds(segment.get("end"), default=start + 0.1)
            if end <= start:
                end = start + 0.1
            text = self._build_ass_karaoke_text(segment, start, end)
            if not text:
                continue
            events.append(
                "Dialogue: 0,"
                f"{self._seconds_to_ass_time(start)},{self._seconds_to_ass_time(end)},"
                f"Default,,0,0,0,,{text}"
            )

        if not events:
            raise PipelineError(
                "Dubbed transcript has no usable text for ASS subtitles"
            )

        header = """[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,8,&H00FFFFFF,&H0000D7FF,&H00202020,&H80000000,0,0,0,0,100,100,0,0,1,1,0,5,80,80,56,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        return header + "\n".join(events) + "\n"

    def _build_ass_karaoke_text(
        self, segment: dict[str, object], start: float, end: float
    ) -> str:
        words = segment.get("words")
        if isinstance(words, list) and words:
            parts: list[str] = []
            for raw_word in words:
                if not isinstance(raw_word, dict):
                    continue
                word_text = str(raw_word.get("text") or "").strip()
                if not word_text:
                    continue
                word_start = self._coerce_seconds(raw_word.get("start"), default=start)
                word_end = self._coerce_seconds(raw_word.get("end"), default=word_start)
                centiseconds = max(1, round(max(0.01, word_end - word_start) * 100))
                parts.append(f"{{\\k{centiseconds}}}{self._escape_ass_text(word_text)}")
            if parts:
                return " ".join(parts)

        text = str(segment.get("text") or "").strip()
        if not text:
            return ""
        centiseconds = max(1, round(max(0.01, end - start) * 100))
        return f"{{\\k{centiseconds}}}{self._escape_ass_text(text)}"

    def _escape_ass_text(self, value: str) -> str:
        return (
            value.replace("\\", r"\\")
            .replace("{", r"\{")
            .replace("}", r"\}")
            .replace("\n", r"\N")
        )

    def _seconds_to_ass_time(self, seconds: float) -> str:
        total_centiseconds = max(0, int(round(seconds * 100)))
        centiseconds = total_centiseconds % 100
        total_seconds = total_centiseconds // 100
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        whole_seconds = total_seconds % 60
        return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"

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
        job_id: int | None = None,
    ) -> None:
        if output_video_speed <= 0:
            raise PipelineError("output_video_speed must be positive")
        if original_audio_volume < 0:
            raise PipelineError("original_audio_volume must be non-negative")

        if subtitles.suffix.lower() == ".ass":
            subtitle_filter = f"ass={self._escape_ffmpeg_filter_path(subtitles)}"
        else:
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
        self._run_cmd(cmd, "audio/video/subtitle burn-in failed", job_id=job_id)

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

    def _run_cmd(
        self, cmd: list[str], error_message: str, *, job_id: int | None = None
    ) -> None:
        if job_id is None:
            run_cmd(cmd, error_message, PipelineError)
            return

        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                try:
                    self._raise_if_canceled(job_id)
                except JobCanceled:
                    process.terminate()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate(timeout=5)
                    raise
        if process.returncode != 0:
            details = stderr.strip() or stdout.strip()
            raise PipelineError(f"{error_message}: {details}")

    def _raise_if_canceled(self, job_id: int) -> None:
        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if job and job.status == JobStatus.CANCELED:
                raise JobCanceled()

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
        if job.status == JobStatus.CANCELED:
            raise JobCanceled()
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
            if job.status == JobStatus.CANCELED:
                return
            job.status = JobStatus.FAILED
            job.error_code = error_code
            job.error_message = error_message[:1024]
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()
            job_update_broker.notify(job.id, "job_failed")

    def _mark_job_canceled(self, job_id: int) -> None:
        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return
            job.status = JobStatus.CANCELED
            job.current_step = "canceled"
            job.updated_at = datetime.now(timezone.utc)
            job.error_code = None
            job.error_message = None
            session.add(job)
            session.commit()
            job_update_broker.notify(job.id, "job_canceled")

    def _seconds_to_srt_time(self, seconds: float) -> str:
        safe_seconds = max(0.0, float(seconds))
        millis_total = int(round(safe_seconds * 1000))
        hours, remainder = divmod(millis_total, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, millis = divmod(remainder, 1_000)
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


video_processing_worker = VideoProcessingWorker()
