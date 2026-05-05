from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.database import get_session
from app.models.entities import ProviderRequest, Job

router = APIRouter(prefix="/v1/provider-requests", tags=["provider_requests"])


@router.get("/job/{job_id}", response_model=list[ProviderRequest])
def list_provider_requests_for_job(job_id: int, session: Session = Depends(get_session)):
    job = session.exec(select(Job).where(Job.id == job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return list(session.exec(select(ProviderRequest).where(ProviderRequest.job_id == job_id)).all())
