from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select

from app.db.database import get_session
from app.models.entities import Artifact, Job

router = APIRouter(prefix="/v1/artifacts", tags=["artifacts"])


@router.get("/job/{job_id}", response_model=list[Artifact])
def list_artifacts_for_job(job_id: int, session: Session = Depends(get_session)):
    job = session.exec(select(Job).where(Job.id == job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return list(session.exec(select(Artifact).where(Artifact.job_id == job.id)).all())
