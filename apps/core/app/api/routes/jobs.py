from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.database import get_session
from app.models.entities import Job
from app.schemas.jobs import JobCreateRequest, JobResponse

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=201)
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


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.exec(select(Job).where(Job.id == job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
