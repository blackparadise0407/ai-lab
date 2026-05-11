from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
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
    "/{artifact_id}/preview",
    summary="Preview an artifact",
    description=(
        "Returns a local artifact file for inline preview. Video artifacts support "
        "HTTP byte ranges for browser seeking. Externally hosted artifacts redirect "
        "to their storage URL."
    ),
)
def preview_artifact(
    artifact_id: int,
    range_header: str | None = Header(default=None, alias="Range"),
    session: Session = Depends(get_session),
):
    artifact = _get_artifact_or_404(artifact_id, session)

    if artifact.storage_url.startswith(("http://", "https://")):
        return RedirectResponse(url=artifact.storage_url)

    artifact_path = Path(artifact.storage_url)
    if not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found")

    media_type = artifact.content_type or "application/octet-stream"
    if _is_video_artifact(artifact):
        return _video_preview_response(artifact_path, media_type, range_header)

    return FileResponse(
        path=artifact_path,
        media_type=media_type,
        filename=artifact_path.name,
        content_disposition_type="inline",
    )


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
    artifact = _get_artifact_or_404(artifact_id, session)

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


def _get_artifact_or_404(artifact_id: int, session: Session) -> Artifact:
    artifact = session.exec(select(Artifact).where(Artifact.id == artifact_id)).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


def _is_video_artifact(artifact: Artifact) -> bool:
    return bool(artifact.content_type and artifact.content_type.startswith("video/"))


def _video_preview_response(
    artifact_path: Path,
    media_type: str,
    range_header: str | None,
):
    file_size = artifact_path.stat().st_size
    if range_header is None:
        return FileResponse(
            path=artifact_path,
            media_type=media_type,
            filename=artifact_path.name,
            content_disposition_type="inline",
            headers={"Accept-Ranges": "bytes"},
        )

    byte_range = _parse_byte_range(range_header, file_size)
    if byte_range is None:
        return StreamingResponse(
            iter(()),
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes */{file_size}",
            },
        )

    start, end = byte_range
    content_length = end - start + 1
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(content_length),
    }
    return StreamingResponse(
        _iter_file_range(artifact_path, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers=headers,
    )


def _parse_byte_range(range_header: str, file_size: int) -> tuple[int, int] | None:
    if not range_header.startswith("bytes="):
        return None

    range_spec = range_header.removeprefix("bytes=").strip()
    if "," in range_spec:
        return None

    start_text, separator, end_text = range_spec.partition("-")
    if separator != "-":
        return None

    if start_text == "":
        if not end_text.isdigit():
            return None
        suffix_length = int(end_text)
        if suffix_length <= 0:
            return None
        start = max(file_size - suffix_length, 0)
        end = file_size - 1
    else:
        if not start_text.isdigit() or (end_text and not end_text.isdigit()):
            return None
        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1

    if file_size <= 0 or start >= file_size or start > end:
        return None

    return start, min(end, file_size - 1)


def _iter_file_range(artifact_path: Path, start: int, end: int):
    with artifact_path.open("rb") as artifact_file:
        artifact_file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = artifact_file.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
