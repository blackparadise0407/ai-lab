from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.job_updates import job_update_broker
from app.db.database import get_session
from app.models.entities import (
    Artifact,
    Job,
    JobStatus,
    VideoCollection,
    VideoSegment,
)
from app.schemas.jobs import JobCreateRequest, JobListResponse, JobResponse
from app.services.deletion import delete_job_and_artifacts
from app.services.video_collections import refresh_collection_rollup
from app.workers.video_processor import video_processing_worker

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])

UPLOADS_DIR = Path("uploads/source_videos")
SOURCE_VIDEO_ARTIFACT_TYPE = "source_video"


CANCELABLE_JOB_STATUSES = {
    JobStatus.CREATED,
    JobStatus.UPLOADED,
    JobStatus.PROCESSING,
    JobStatus.WAITING_PROVIDER,
    JobStatus.FINALIZING,
}


def _refresh_job_collection_rollup(session: Session, job_id: int) -> None:
    video_segment = session.exec(
        select(VideoSegment).where(VideoSegment.job_id == job_id)
    ).first()
    if not video_segment:
        return

    collection = session.get(VideoCollection, video_segment.collection_id)
    if collection:
        refresh_collection_rollup(session, collection)


@router.post(
    "",
    response_model=JobResponse,
    status_code=201,
    summary="Create a dubbing job",
    description="Creates a new job and returns its tracking metadata.",
)
def create_job(payload: JobCreateRequest, session: Session = Depends(get_session)):
    job = Job(
        external_job_id=f"job_{uuid4().hex[:12]}",
        source_language=payload.source_language,
        target_language=payload.target_language,
        translation_context=payload.translation_context,
        voice_id=payload.voice_id,
        output_video_speed=payload.output_video_speed,
        original_audio_volume=payload.original_audio_volume,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    job_update_broker.notify(job.id, "job_created")

    return job


@router.post(
    "/{job_id}/video",
    response_model=JobResponse,
    summary="Upload source video",
    description="Uploads a source video file for a job and marks the job as uploaded.",
)
async def upload_source_video(
    job_id: int,
    file: UploadFile = File(..., description="Video file (e.g. .mp4, .mov)"),
    session: Session = Depends(get_session),
):
    job = session.exec(select(Job).where(Job.id == job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="Only video files are supported")

    extension = Path(file.filename or "video").suffix or ".mp4"
    upload_path = UPLOADS_DIR / f"job_{job_id}_{uuid4().hex[:8]}{extension}"
    upload_path.parent.mkdir(parents=True, exist_ok=True)

    with upload_path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            output.write(chunk)

    existing_artifact = session.exec(
        select(Artifact).where(
            Artifact.job_id == job_id,
            Artifact.artifact_type == SOURCE_VIDEO_ARTIFACT_TYPE,
        )
    ).first()

    storage_url = str(upload_path)
    if existing_artifact:
        existing_artifact.storage_url = storage_url
        existing_artifact.content_type = file.content_type
    else:
        artifact = Artifact(
            job_id=job_id,
            artifact_type=SOURCE_VIDEO_ARTIFACT_TYPE,
            storage_url=storage_url,
            content_type=file.content_type,
        )
        session.add(artifact)

    job.status = JobStatus.UPLOADED
    job.current_step = "source_video_uploaded"
    job.progress_percent = max(job.progress_percent, 5)

    session.add(job)
    session.commit()
    session.refresh(job)

    job_update_broker.notify(job.id, "source_video_uploaded")
    video_processing_worker.enqueue(job_id=job.id)
    return job


@router.post(
    "/{job_id}/retry",
    response_model=JobResponse,
    summary="Retry failed job",
    description="Re-queues a failed job for processing using its existing source video artifact.",
)
def retry_job(job_id: int, session: Session = Depends(get_session)):
    job = session.exec(select(Job).where(Job.id == job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.FAILED:
        raise HTTPException(status_code=409, detail="Only failed jobs can be retried")

    source_artifact = session.exec(
        select(Artifact).where(
            Artifact.job_id == job_id,
            Artifact.artifact_type == SOURCE_VIDEO_ARTIFACT_TYPE,
        )
    ).first()
    if not source_artifact:
        raise HTTPException(status_code=400, detail="Job has no source video to retry")

    source_video_path = Path(source_artifact.storage_url)
    if not source_video_path.exists():
        raise HTTPException(status_code=400, detail="Source video file not found")

    retry_from_step = job.current_step
    job.status = JobStatus.UPLOADED
    job.current_step = "retry_queued"
    job.progress_percent = max(job.progress_percent, 5)
    job.error_code = None
    job.error_message = None
    session.add(job)
    session.commit()
    session.refresh(job)

    video_segment = session.exec(
        select(VideoSegment).where(VideoSegment.job_id == job_id)
    ).first()
    if video_segment:
        collection = session.get(VideoCollection, video_segment.collection_id)
        if collection:
            refresh_collection_rollup(session, collection)

    job_update_broker.notify(job.id, "job_retry_queued")
    video_processing_worker.enqueue(job_id=job.id, retry_from_step=retry_from_step)
    return job


@router.post(
    "/{job_id}/cancel",
    response_model=JobResponse,
    summary="Cancel job",
    description="Marks a queued or in-progress job as canceled. The worker stops at the next cancellation checkpoint.",
)
def cancel_job(job_id: int, session: Session = Depends(get_session)):
    job = session.exec(select(Job).where(Job.id == job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == JobStatus.CANCELED:
        return job

    if job.status not in CANCELABLE_JOB_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Only queued or in-progress jobs can be canceled",
        )

    job.status = JobStatus.CANCELED
    job.current_step = "canceled"
    job.updated_at = datetime.now(timezone.utc)
    job.error_code = None
    job.error_message = None
    session.add(job)
    session.commit()
    session.refresh(job)

    _refresh_job_collection_rollup(session, job.id)
    job_update_broker.notify(job.id, "job_canceled")
    return job


@router.delete(
    "/{job_id}",
    status_code=204,
    summary="Delete job",
    description="Deletes a job, its provider request history, database artifact records, and local artifact files.",
)
def delete_job(job_id: int, session: Session = Depends(get_session)):
    job = session.exec(select(Job).where(Job.id == job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    delete_job_and_artifacts(session, job)
    return None


@router.get(
    "",
    response_model=JobListResponse,
    summary="List jobs",
    description="Lists a paginated set of jobs sorted by created time, with optional status, language, and current-step filters.",
)
def list_jobs(
    status: JobStatus | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    current_step: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    count_statement = select(func.count(Job.id))
    statement = select(Job).order_by(Job.created_at.desc()).offset(offset).limit(limit)

    filters = []
    if status is not None:
        filters.append(Job.status == status)
    if source_language:
        filters.append(Job.source_language == source_language)
    if target_language:
        filters.append(Job.target_language == target_language)
    if current_step:
        filters.append(Job.current_step == current_step)

    for filter_clause in filters:
        count_statement = count_statement.where(filter_clause)
        statement = statement.where(filter_clause)

    total = session.exec(count_statement).one()
    items = list(session.exec(statement).all())
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Get job details",
    description="Returns the current status and metadata for a job.",
)
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.exec(select(Job).where(Job.id == job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
