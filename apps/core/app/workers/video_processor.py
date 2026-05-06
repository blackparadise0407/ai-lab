from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, select
from faster_whisper import WhisperModel

from app.db.database import engine
from app.models.entities import Artifact, Job, JobStatus, ProviderRequest, ProviderRequestStatus

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
        self._queue: queue.Queue[int] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="video-processing-worker", daemon=True)

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(-1)
        self._thread.join(timeout=5)

    def enqueue(self, job_id: int) -> None:
        self._queue.put(job_id)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            job_id = self._queue.get()
            if job_id == -1:
                self._queue.task_done()
                continue
            try:
                self._process_job(job_id)
            finally:
                self._queue.task_done()

    def _process_job(self, job_id: int) -> None:
        try:
            self._process_job_impl(job_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Video processing failed for job_id=%s", job_id)
            self._mark_job_failed(job_id, "pipeline_error", str(exc))

    def _process_job_impl(self, job_id: int) -> None:
        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job or job.status not in (JobStatus.UPLOADED, JobStatus.PROCESSING):
                return
            target_language = job.target_language

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

            self._update_job_progress(session, job, "extracting_audio", 10)

        WORK_DIR.mkdir(parents=True, exist_ok=True)
        PROCESSED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        job_work_dir = WORK_DIR / f"job_{job_id}"
        job_work_dir.mkdir(parents=True, exist_ok=True)

        source_audio_path = job_work_dir / "source.wav"
        self._extract_audio(source_video_path, source_audio_path)

        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return
            self._update_job_progress(session, job, "transcribing", 30)

        srt_source_text = self._transcribe_to_srt(source_audio_path)
        srt_source_path = job_work_dir / "source.srt"
        srt_source_path.write_text(srt_source_text, encoding="utf-8")

        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return
            self._update_job_progress(session, job, "translating", 45)

        translated_srt_text = self._translate_srt(srt_source_text, target_language)
        translated_srt_path = job_work_dir / "translated.srt"
        translated_srt_path.write_text(translated_srt_text, encoding="utf-8")

        ssml_text = self._compile_ssml(translated_srt_text)
        ssml_path = job_work_dir / "dub.ssml"
        ssml_path.write_text(ssml_text, encoding="utf-8")

        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return
            self._update_job_progress(session, job, "waiting_provider", 65, status=JobStatus.WAITING_PROVIDER)

        tts_audio_path, provider_request_id = self._submit_dub_request(job_id, ssml_text, job_work_dir)

        with Session(engine) as session:
            self._upsert_provider_request(session, job_id, provider_request_id)
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return
            self._update_job_progress(session, job, "muxing", 85, status=JobStatus.FINALIZING)

        output_path = PROCESSED_OUTPUT_DIR / f"job_{job_id}_dubbed.mp4"
        self._mux_audio(source_video_path, tts_audio_path, translated_srt_path, output_path)

        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return

            self._upsert_artifact(session, job_id, PROCESSED_ARTIFACT_TYPE, output_path, "video/mp4")
            self._upsert_artifact(session, job_id, SRT_ARTIFACT_TYPE, translated_srt_path, "application/x-subrip")
            self._upsert_artifact(session, job_id, TTS_AUDIO_ARTIFACT_TYPE, tts_audio_path, "audio/wav")

            job.status = JobStatus.COMPLETED
            job.current_step = "done"
            job.progress_percent = 100
            job.updated_at = datetime.now(UTC)
            job.error_code = None
            job.error_message = None
            session.add(job)
            session.commit()

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

    def _translate_srt(self, srt_text: str, target_language: str) -> str:
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            return srt_text

        model = os.getenv("OPENAI_TRANSLATION_MODEL", "gpt-4.1-mini")

        blocks = self._parse_srt_blocks(srt_text)
        if not blocks:
            return srt_text

        translated_texts = self._translate_lines_with_openai(
            openai_api_key=openai_api_key,
            model=model,
            target_language=target_language,
            lines=[block[2] for block in blocks],
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

    def _translate_lines_with_openai(
        self,
        *,
        openai_api_key: str,
        model: str,
        target_language: str,
        lines: list[str],
    ) -> list[str]:
        payload = {
            "model": model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You are a professional subtitle translator and dubbing editor. "
                                f"Translate every string in the input JSON array into {target_language}. "
                                "Rules you MUST follow, in priority order:\n"
                                "1. Return ONLY a JSON array of strings — no markdown, no extra keys, no prose.\n"
                                "2. The output array MUST contain exactly the same number of elements as the input array.\n"
                                "3. Element at index N in the output is the translation of element at index N in the input — never merge, split, reorder, or omit elements.\n"
                                "4. DURATION MATCHING (highest priority): Each translated string must have approximately the same spoken duration as its source string. "
                                "Prefer shorter synonyms, contractions, or natural ellipsis over word-for-word accuracy when necessary to match length. "
                                "Aim for the syllable count to be within ±15% of the original.\n"
                                "5. NATURALNESS: Within the duration constraint, use fluent, idiomatic phrasing native to the target language — avoid literal word-for-word translation that sounds unnatural.\n"
                                "6. Preserve the original meaning and emotional tone as closely as possible given constraints 4 and 5.\n"
                                "7. If a line cannot be translated (e.g. it is already in the target language), copy it verbatim."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(lines, ensure_ascii=False)}],
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

        translated = self._parse_openai_translations(translated_raw, expected_count=len(lines))
        if translated is None:
            raise PipelineError("OpenAI translation output was not valid JSON")

        normalized = [str(item).strip() for item in translated]
        if any(not item for item in normalized):
            raise PipelineError("OpenAI translation produced empty subtitle lines")
        return normalized


    def _parse_openai_translations(self, translated_raw: str, expected_count: int) -> list[str] | None:
        parsed = self._json_load_list(translated_raw)
        if parsed is None:
            parsed = self._json_load_list(self._strip_markdown_code_fences(translated_raw))

        if parsed is None:
            return None

        if len(parsed) == expected_count:
            return parsed

        if expected_count == 1:
            return ["\n".join(str(item).strip() for item in parsed if str(item).strip())]

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

    def _compile_ssml(self, translated_srt: str) -> str:
        blocks = self._parse_srt_blocks(translated_srt)
        if not blocks:
            return "No text"

        spoken_blocks: list[tuple[float, float, str]] = []
        for _sequence, timing, text in blocks:
            escaped_text = self._escape_ssml(text).strip()
            if not escaped_text:
                continue
            start_time, end_time = self._parse_srt_timing_range(timing)
            spoken_blocks.append((start_time, end_time, escaped_text))

        if not spoken_blocks:
            return "No text"

        parts: list[str] = []
        for idx, (_start_time, end_time, text) in enumerate(spoken_blocks):
            parts.append(text)
            if idx >= len(spoken_blocks) - 1:
                continue

            next_start_time = spoken_blocks[idx + 1][0]
            pause_seconds = max(0.0, next_start_time - end_time)
            rounded_pause_seconds = round(pause_seconds, 3)
            if rounded_pause_seconds >= 0.01:
                parts.append(f"<break time={rounded_pause_seconds:.2f}s/>")
            else:
                parts.append(" ")

        return "".join(parts).strip() or "No text"

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

    def _submit_dub_request(self, job_id: int, ssml: str, job_work_dir: Path) -> tuple[Path, str]:
        provider_url = os.getenv("DUB_PROVIDER_URL")
        provider_app_id = os.getenv("DUB_PROVIDER_APP_ID")
        provider_token = os.getenv("DUB_PROVIDER_TOKEN")
        output_audio = job_work_dir / "dubbed.wav"
        if not provider_url:
            output_audio.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
            return output_audio, f"mock-{job_id}"
        if not provider_app_id or not provider_token:
            raise PipelineError("DUB_PROVIDER_APP_ID and DUB_PROVIDER_TOKEN are required when DUB_PROVIDER_URL is set")

        payload = json.dumps(
            {
                "app_id": provider_app_id,
                "input_text": ssml,
                "audio_type": "wav",
                "response_type": "direct",
                "voice_code": "hn_female_ngochuyen_full_48k-fhg",
            }
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider_token}",
        }
        create_request = urllib.request.Request(
            provider_url,
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(create_request, timeout=60) as response:  # noqa: S310
                create_response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise PipelineError(f"Dub provider request failed: {exc}") from exc

        provider_request_id = str(create_response_data.get("result", {}).get("request_id") or f"provider-{job_id}")
        audio_url = self._wait_for_audio_url(provider_url, provider_request_id, headers)
        self._download_file(audio_url, output_audio)
        return output_audio, provider_request_id

    def _wait_for_audio_url(self, provider_url: str, provider_request_id: str, headers: dict[str, str]) -> str:
        status_url = f"{provider_url.rstrip('/')}/{provider_request_id}"
        for _ in range(30):
            request = urllib.request.Request(status_url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                    status_response_data = json.loads(response.read().decode("utf-8"))
            except urllib.error.URLError as exc:
                raise PipelineError(f"Dub provider status check failed: {exc}") from exc

            result = status_response_data.get("result", {})
            request_status = result.get("status")
            audio_url = result.get("audio_link")
            if request_status == "SUCCESS" and audio_url:
                return str(audio_url)
            if request_status == "FAILURE":
                raise PipelineError("Dub provider synthesis request failed")
            time.sleep(2)

        raise PipelineError("Timed out waiting for dub provider audio")

    def _mux_audio(self, source_video: Path, dubbed_audio: Path, subtitles: Path, output_video: Path) -> None:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-i",
            str(dubbed_audio),
            "-i",
            str(subtitles),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-map",
            "2:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-c:s",
            "mov_text",
            "-shortest",
            str(output_video),
        ]
        self._run_cmd(cmd, "audio/video/subtitle muxing failed")

    def _run_cmd(self, cmd: list[str], error_message: str) -> None:
        process = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if process.returncode != 0:
            details = process.stderr.strip() or process.stdout.strip()
            raise PipelineError(f"{error_message}: {details}")

    def _download_file(self, url: str, output_path: Path) -> None:
        try:
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
                output_path.write_bytes(response.read())
        except urllib.error.URLError as exc:
            raise PipelineError(f"Failed to download dubbed audio: {exc}") from exc

    def _upsert_provider_request(self, session: Session, job_id: int, provider_request_id: str) -> None:
        provider_request = session.exec(
            select(ProviderRequest).where(ProviderRequest.provider_request_id == provider_request_id)
        ).first()
        if provider_request:
            provider_request.status = ProviderRequestStatus.SUCCEEDED
            provider_request.callback_received = True
            provider_request.updated_at = datetime.now(UTC)
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

    def _upsert_artifact(self, session: Session, job_id: int, artifact_type: str, path: Path, content_type: str) -> None:
        artifact = session.exec(
            select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == artifact_type)
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
        job.updated_at = datetime.now(UTC)
        session.add(job)
        session.commit()

    def _mark_job_failed(self, job_id: int, error_code: str, error_message: str) -> None:
        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return
            job.status = JobStatus.FAILED
            job.current_step = "failed"
            job.error_code = error_code
            job.error_message = error_message[:1024]
            job.updated_at = datetime.now(UTC)
            session.add(job)
            session.commit()

    def _escape_ssml(self, text: str) -> str:
        return re.sub(r"[<>&\"]", lambda m: {"<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;"}[m.group(0)], text)

    def _seconds_to_srt_time(self, seconds: float) -> str:
        safe_seconds = max(0.0, float(seconds))
        millis_total = int(round(safe_seconds * 1000))
        hours, remainder = divmod(millis_total, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, millis = divmod(remainder, 1_000)
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


video_processing_worker = VideoProcessingWorker()