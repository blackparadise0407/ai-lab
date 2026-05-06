from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.job_updates import job_update_broker
from app.db.database import get_session
from app.models.entities import Artifact, ConnectedAccount, Job, JobStatus, ProviderRequest, ProviderRequestStatus
from app.providers.upload_provider import UploadCredentials, UploadProviderClient, UploadProviderError, UploadRequest
from app.schemas.uploads import JobUploadPublishRequest, JobUploadPublishResponse
from app.workers.video_processor import PROCESSED_ARTIFACT_TYPE

router = APIRouter(prefix="/v1/jobs", tags=["uploads"])

upload_provider_client = UploadProviderClient()


@router.post(
    "/{job_id}/uploads",
    response_model=JobUploadPublishResponse,
    summary="Upload completed video to a publishing platform",
    description="Publishes the completed dubbed video through a platform-specific upload adapter.",
)
def publish_completed_video(
    job_id: int,
    payload: JobUploadPublishRequest,
    session: Session = Depends(get_session),
):
    job = session.exec(select(Job).where(Job.id == job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Job must be completed before publishing")

    artifact = session.exec(
        select(Artifact).where(
            Artifact.job_id == job_id,
            Artifact.artifact_type == PROCESSED_ARTIFACT_TYPE,
        )
    ).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Completed video artifact not found")

    video_path = Path(artifact.storage_url)
    try:
        upload_credentials = _get_upload_credentials(session, payload)
        result = upload_provider_client.upload(
            payload.platform,
            UploadRequest(
                job_id=job_id,
                video_path=video_path,
                title=payload.title,
                description=payload.description,
                privacy=payload.privacy,
            ),
            credentials=upload_credentials,
        )
    except UploadProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _upsert_upload_provider_request(
        session=session,
        job_id=job_id,
        provider_name=f"upload_{result.platform}",
        provider_request_id=result.provider_request_id,
    )
    job_update_broker.notify(job_id, "video_published")

    return JobUploadPublishResponse(
        job_id=job_id,
        platform=result.platform,
        provider_request_id=result.provider_request_id,
        remote_url=result.remote_url,
        status=ProviderRequestStatus.SUCCEEDED.value,
    )


def _upsert_upload_provider_request(
    *,
    session: Session,
    job_id: int,
    provider_name: str,
    provider_request_id: str,
) -> None:
    provider_request = session.exec(
        select(ProviderRequest).where(ProviderRequest.provider_request_id == provider_request_id)
    ).first()
    if provider_request:
        provider_request.provider_name = provider_name
        provider_request.status = ProviderRequestStatus.SUCCEEDED
        provider_request.callback_received = True
        provider_request.updated_at = datetime.now(timezone.utc)
    else:
        provider_request = ProviderRequest(
            job_id=job_id,
            provider_name=provider_name,
            provider_request_id=provider_request_id,
            status=ProviderRequestStatus.SUCCEEDED,
            callback_received=True,
        )
        session.add(provider_request)
    session.commit()


def _get_upload_credentials(
    session: Session,
    payload: JobUploadPublishRequest,
) -> UploadCredentials | None:
    if payload.connected_account_id is None:
        return None

    connected_account = session.get(ConnectedAccount, payload.connected_account_id)
    if not connected_account:
        raise HTTPException(status_code=404, detail="Connected account not found")

    platform = payload.platform.strip().lower()
    if connected_account.platform != platform:
        raise HTTPException(
            status_code=400,
            detail="Connected account platform does not match the requested upload platform",
        )

    scopes = tuple(scope for scope in connected_account.scopes.split() if scope)
    return UploadCredentials(
        access_token=connected_account.access_token,
        refresh_token=connected_account.refresh_token,
        token_uri=os.getenv("YOUTUBE_TOKEN_URI", "https://oauth2.googleapis.com/token") if platform == "youtube" else None,
        client_id=os.getenv("YOUTUBE_CLIENT_ID") if platform == "youtube" else None,
        client_secret=os.getenv("YOUTUBE_CLIENT_SECRET") if platform == "youtube" else None,
        scopes=scopes,
    )
