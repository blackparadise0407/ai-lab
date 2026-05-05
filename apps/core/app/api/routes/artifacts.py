from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db.database import get_session
from app.models.entities import Artifact

router = APIRouter(prefix="/v1/artifacts", tags=["artifacts"])


@router.get("/job/{job_id}", response_model=list[Artifact])
def list_artifacts_for_job(job_id: int, session: Session = Depends(get_session)):
    return list(session.exec(select(Artifact).where(Artifact.job_id == job_id)).all())
