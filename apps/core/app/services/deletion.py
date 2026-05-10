from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from app.models.entities import (
    Artifact,
    Job,
    ProviderRequest,
    VideoCollection,
    VideoSegment,
)
from app.services.video_collections import refresh_collection_rollup


def delete_job_and_artifacts(session: Session, job: Job) -> None:
    """Delete a job, its dependent records, and any local artifact files."""
    if job.id is None:
        return

    artifact_paths = _artifact_paths_for_job(session, job.id)
    video_segment = session.exec(
        select(VideoSegment).where(VideoSegment.job_id == job.id)
    ).first()
    collection_id = video_segment.collection_id if video_segment else None

    if collection_id is not None:
        collection = session.get(VideoCollection, collection_id)
        if collection:
            _set_next_collection_source_artifact(
                session, collection, excluding_job_id=job.id
            )

    _delete_job_records(session, job.id)
    session.commit()

    _delete_local_files(artifact_paths)

    if collection_id is not None:
        collection = session.get(VideoCollection, collection_id)
        if collection:
            refresh_collection_rollup(session, collection)


def delete_collection_and_artifacts(
    session: Session, collection: VideoCollection
) -> None:
    """Delete a collection, all segment jobs, and any local artifact files."""
    if collection.id is None:
        return

    segments = list(
        session.exec(
            select(VideoSegment).where(VideoSegment.collection_id == collection.id)
        ).all()
    )
    job_ids = [segment.job_id for segment in segments]
    artifact_paths = _artifact_paths_for_jobs(session, job_ids)

    session.delete(collection)
    for job_id in job_ids:
        _delete_job_records(session, job_id)
    session.commit()

    _delete_local_files(artifact_paths)


def _delete_job_records(session: Session, job_id: int) -> None:
    for provider_request in session.exec(
        select(ProviderRequest).where(ProviderRequest.job_id == job_id)
    ).all():
        session.delete(provider_request)

    for segment in session.exec(
        select(VideoSegment).where(VideoSegment.job_id == job_id)
    ).all():
        session.delete(segment)

    for artifact in session.exec(
        select(Artifact).where(Artifact.job_id == job_id)
    ).all():
        session.delete(artifact)

    job = session.get(Job, job_id)
    if job:
        session.delete(job)


def _set_next_collection_source_artifact(
    session: Session, collection: VideoCollection, excluding_job_id: int
) -> None:
    next_segment = session.exec(
        select(VideoSegment)
        .where(
            VideoSegment.collection_id == collection.id,
            VideoSegment.job_id != excluding_job_id,
            VideoSegment.source_artifact_id.is_not(None),
        )
        .order_by(VideoSegment.sequence_index)
    ).first()
    collection.source_artifact_id = (
        next_segment.source_artifact_id if next_segment else None
    )
    session.add(collection)


def _artifact_paths_for_job(session: Session, job_id: int) -> list[Path]:
    return _artifact_paths_for_jobs(session, [job_id])


def _artifact_paths_for_jobs(session: Session, job_ids: list[int]) -> list[Path]:
    if not job_ids:
        return []

    artifacts = session.exec(
        select(Artifact).where(Artifact.job_id.in_(job_ids))
    ).all()
    paths: list[Path] = []
    for artifact in artifacts:
        storage_url = artifact.storage_url
        if storage_url.startswith(("http://", "https://")):
            continue
        paths.append(Path(storage_url))
    return paths


def _delete_local_files(paths: list[Path]) -> None:
    for path in paths:
        if path.is_file():
            path.unlink(missing_ok=True)
            _remove_empty_parents(path.parent)


def _remove_empty_parents(path: Path) -> None:
    stop_at = Path.cwd().resolve()
    current = path.resolve()
    while current != stop_at and stop_at in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
