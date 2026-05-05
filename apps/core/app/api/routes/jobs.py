from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from app.db.database import get_session
from app.models.entities import Artifact, Job, JobStatus
from app.schemas.jobs import JobCreateRequest, JobResponse
from app.workers.video_processor import video_processing_worker

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])

UPLOADS_DIR = Path("uploads/source_videos")
SOURCE_VIDEO_ARTIFACT_TYPE = "source_video"


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
    )
    session.add(job)
    session.commit()
    session.refresh(job)

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

    video_processing_worker.enqueue(job_id=job.id)
    return job


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
