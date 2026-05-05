from __future__ import annotations

import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from app.db.database import engine
from app.models.entities import Artifact, Job, JobStatus

PROCESSED_ARTIFACT_TYPE = "dubbed_video"
PROCESSED_OUTPUT_DIR = Path("uploads/processed_videos")


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
        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job or job.status not in (JobStatus.UPLOADED, JobStatus.PROCESSING):
                return

            job.status = JobStatus.PROCESSING
            job.current_step = "transcribing"
            job.progress_percent = max(job.progress_percent, 20)
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()

        time.sleep(1)

        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return
            job.status = JobStatus.FINALIZING
            job.current_step = "muxing"
            job.progress_percent = max(job.progress_percent, 80)
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()

        time.sleep(1)

        with Session(engine) as session:
            job = session.exec(select(Job).where(Job.id == job_id)).first()
            if not job:
                return

            PROCESSED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            output_path = PROCESSED_OUTPUT_DIR / f"job_{job_id}_dubbed.mp4"
            output_path.write_bytes(b"mock dubbed output")

            artifact = session.exec(
                select(Artifact).where(
                    Artifact.job_id == job_id,
                    Artifact.artifact_type == PROCESSED_ARTIFACT_TYPE,
                )
            ).first()

            if artifact:
                artifact.storage_url = str(output_path)
                artifact.content_type = "video/mp4"
            else:
                artifact = Artifact(
                    job_id=job_id,
                    artifact_type=PROCESSED_ARTIFACT_TYPE,
                    storage_url=str(output_path),
                    content_type="video/mp4",
                )
                session.add(artifact)

            job.status = JobStatus.COMPLETED
            job.current_step = "done"
            job.progress_percent = 100
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()


video_processing_worker = VideoProcessingWorker()
