from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
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


@router.get(
    "/{artifact_id}/download",
    summary="Download an artifact",
    description="Streams a local artifact file or redirects to externally hosted artifact storage.",
)
def download_artifact(
    artifact_id: int,
    disposition: str = Query(default="attachment", pattern="^(attachment|inline)$"),
    session: Session = Depends(get_session),
):
    artifact = session.exec(select(Artifact).where(Artifact.id == artifact_id)).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.storage_url.startswith(("http://", "https://")):
        return RedirectResponse(url=artifact.storage_url)

    artifact_path = Path(artifact.storage_url)
    if not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found")

    return FileResponse(
        path=artifact_path,
        media_type=artifact.content_type or "application/octet-stream",
        filename=artifact_path.name,
        content_disposition_type=disposition,
    )
