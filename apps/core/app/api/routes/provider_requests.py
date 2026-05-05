from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db.database import get_session
from app.models.entities import ProviderRequest

router = APIRouter(prefix="/v1/provider-requests", tags=["provider_requests"])


@router.get("/job/{job_id}", response_model=list[ProviderRequest])
def list_provider_requests_for_job(job_id: int, session: Session = Depends(get_session)):
    return list(session.exec(select(ProviderRequest).where(ProviderRequest.job_id == job_id)).all())
