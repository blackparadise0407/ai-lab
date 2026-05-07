from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.entities import Artifact, Job, JobStatus, VideoCollection, VideoSegment
from app.workers.video_processor import PROCESSED_ARTIFACT_TYPE


def refresh_collection_rollup(session: Session, collection: VideoCollection) -> VideoCollection:
    segments = list(
        session.exec(
            select(VideoSegment).where(VideoSegment.collection_id == collection.id).order_by(VideoSegment.sequence_index)
        ).all()
    )
    jobs_by_id: dict[int, Job] = {}
    if segments:
        jobs = session.exec(select(Job).where(Job.id.in_([segment.job_id for segment in segments]))).all()
        jobs_by_id = {job.id: job for job in jobs if job.id is not None}

    collection.segment_count = len(segments)
    collection.completed_segment_count = sum(
        1 for segment in segments if jobs_by_id.get(segment.job_id) is not None and jobs_by_id[segment.job_id].status == JobStatus.COMPLETED
    )
    if segments:
        collection.progress_percent = round(
            sum(jobs_by_id.get(segment.job_id).progress_percent if jobs_by_id.get(segment.job_id) else 0 for segment in segments)
            / len(segments)
        )
        job_statuses = [jobs_by_id[segment.job_id].status for segment in segments if segment.job_id in jobs_by_id]
        if job_statuses and all(status == JobStatus.COMPLETED for status in job_statuses):
            collection.status = JobStatus.COMPLETED
        elif any(status == JobStatus.FAILED for status in job_statuses):
            collection.status = JobStatus.FAILED
        elif any(status in (JobStatus.PROCESSING, JobStatus.WAITING_PROVIDER, JobStatus.FINALIZING) for status in job_statuses):
            collection.status = JobStatus.PROCESSING
        elif any(status == JobStatus.UPLOADED for status in job_statuses):
            collection.status = JobStatus.UPLOADED
    collection.updated_at = datetime.now(timezone.utc)

    for segment in segments:
        processed_artifact = session.exec(
            select(Artifact).where(
                Artifact.job_id == segment.job_id,
                Artifact.artifact_type == PROCESSED_ARTIFACT_TYPE,
            )
        ).first()
        if processed_artifact:
            segment.processed_artifact_id = processed_artifact.id
            segment.updated_at = datetime.now(timezone.utc)
            session.add(segment)

    session.add(collection)
    session.commit()
    session.refresh(collection)
    return collection
