from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.job_updates import job_update_broker
from app.db.database import get_session
from app.models.entities import Artifact, Job, JobStatus, VideoCollection, VideoSegment
from app.schemas.jobs import JobResponse
from app.schemas.video_collections import (
    VideoCollectionCreateRequest,
    VideoCollectionDetailResponse,
    VideoCollectionListResponse,
    VideoCollectionResponse,
    VideoSegmentArtifactResponse,
    VideoSegmentResponse,
)
from app.services.video_collections import refresh_collection_rollup
from app.services.video_splitter import VideoSplitError, split_video
from app.workers.video_processor import SOURCE_VIDEO_ARTIFACT_TYPE, PROCESSED_ARTIFACT_TYPE, video_processing_worker

router = APIRouter(prefix="/v1/video-collections", tags=["video_collections"])

COLLECTION_UPLOADS_DIR = Path("uploads/source_videos")
COLLECTION_SEGMENTS_DIR = Path("uploads/source_segments")


@router.post("", response_model=VideoCollectionResponse, status_code=201, summary="Create a video collection")
def create_video_collection(
    payload: VideoCollectionCreateRequest,
    session: Session = Depends(get_session),
):
    collection = VideoCollection(
        external_collection_id=f"vc_{uuid4().hex[:12]}",
        title=payload.title,
        source_language=payload.source_language,
        target_language=payload.target_language,
        split_threshold_seconds=payload.split_threshold_seconds,
    )
    session.add(collection)
    session.commit()
    session.refresh(collection)
    return collection


@router.get("", response_model=VideoCollectionListResponse, summary="List video collections")
def list_video_collections(
    status: JobStatus | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    count_statement = select(func.count(VideoCollection.id))
    statement = select(VideoCollection).order_by(VideoCollection.updated_at.desc()).offset(offset).limit(limit)
    if status is not None:
        count_statement = count_statement.where(VideoCollection.status == status)
        statement = statement.where(VideoCollection.status == status)

    total = session.exec(count_statement).one()
    collections = list(session.exec(statement).all())
    items = [refresh_collection_rollup(session, collection) for collection in collections]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{collection_id}", response_model=VideoCollectionDetailResponse, summary="Get video collection details")
def get_video_collection(collection_id: int, session: Session = Depends(get_session)):
    collection = _get_collection_or_404(session, collection_id)
    collection = refresh_collection_rollup(session, collection)
    return _collection_detail_response(session, collection)


@router.post(
    "/{collection_id}/video",
    response_model=VideoCollectionDetailResponse,
    summary="Upload and split a source video for a collection",
)
async def upload_collection_video(
    collection_id: int,
    file: UploadFile = File(..., description="Video file (e.g. .mp4, .mov)"),
    session: Session = Depends(get_session),
):
    collection = _get_collection_or_404(session, collection_id)
    existing_segment = session.exec(select(VideoSegment).where(VideoSegment.collection_id == collection.id)).first()
    if existing_segment:
        raise HTTPException(status_code=409, detail="Collection already has source video segments")

    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="Only video files are supported")

    extension = Path(file.filename or "video").suffix or ".mp4"
    upload_path = COLLECTION_UPLOADS_DIR / f"collection_{collection_id}_{uuid4().hex[:8]}{extension}"
    upload_path.parent.mkdir(parents=True, exist_ok=True)

    with upload_path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            output.write(chunk)

    segment_output_dir = COLLECTION_SEGMENTS_DIR / f"collection_{collection_id}_{uuid4().hex[:8]}"
    try:
        split_segments = split_video(
            upload_path,
            segment_output_dir,
            max_segment_seconds=collection.split_threshold_seconds,
        )
    except VideoSplitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(timezone.utc)
    collection.original_filename = file.filename
    collection.total_duration_seconds = max(segment.end_seconds for segment in split_segments)
    collection.status = JobStatus.UPLOADED
    collection.segment_count = len(split_segments)
    collection.progress_percent = 5
    collection.updated_at = now
    session.add(collection)
    session.commit()
    session.refresh(collection)

    first_artifact_id: int | None = None
    enqueued_job_ids: list[int] = []
    for segment in split_segments:
        job = Job(
            external_job_id=f"job_{uuid4().hex[:12]}",
            source_language=collection.source_language,
            target_language=collection.target_language,
            status=JobStatus.UPLOADED,
            current_step="source_video_uploaded",
            progress_percent=5,
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        artifact = Artifact(
            job_id=job.id,
            artifact_type=SOURCE_VIDEO_ARTIFACT_TYPE,
            storage_url=str(segment.path),
            content_type=file.content_type,
        )
        session.add(artifact)
        session.commit()
        session.refresh(artifact)

        if first_artifact_id is None:
            first_artifact_id = artifact.id

        video_segment = VideoSegment(
            collection_id=collection.id,
            job_id=job.id,
            sequence_index=segment.sequence_index,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            duration_seconds=segment.duration_seconds,
            source_artifact_id=artifact.id,
        )
        session.add(video_segment)
        session.commit()
        enqueued_job_ids.append(job.id)
        job_update_broker.notify(job.id, "source_video_uploaded")

    collection.source_artifact_id = first_artifact_id
    session.add(collection)
    session.commit()
    collection = refresh_collection_rollup(session, collection)

    for job_id in enqueued_job_ids:
        video_processing_worker.enqueue(job_id=job_id)

    return _collection_detail_response(session, collection)


@router.get(
    "/{collection_id}/segments",
    response_model=list[VideoSegmentResponse],
    summary="List segments for a video collection",
)
def list_video_collection_segments(collection_id: int, session: Session = Depends(get_session)):
    collection = _get_collection_or_404(session, collection_id)
    refresh_collection_rollup(session, collection)
    return _segment_responses(session, collection.id)


def _get_collection_or_404(session: Session, collection_id: int) -> VideoCollection:
    collection = session.exec(select(VideoCollection).where(VideoCollection.id == collection_id)).first()
    if not collection:
        raise HTTPException(status_code=404, detail="Video collection not found")
    return collection


def _collection_detail_response(session: Session, collection: VideoCollection) -> dict:
    data = VideoCollectionResponse.model_validate(collection, from_attributes=True).model_dump()
    data["segments"] = _segment_responses(session, collection.id)
    return data


def _segment_responses(session: Session, collection_id: int) -> list[dict]:
    segments = list(
        session.exec(select(VideoSegment).where(VideoSegment.collection_id == collection_id).order_by(VideoSegment.sequence_index)).all()
    )
    responses: list[dict] = []
    for segment in segments:
        job = session.get(Job, segment.job_id)
        source_artifact = session.get(Artifact, segment.source_artifact_id) if segment.source_artifact_id else None
        processed_artifact = session.get(Artifact, segment.processed_artifact_id) if segment.processed_artifact_id else None
        if processed_artifact is None:
            processed_artifact = session.exec(
                select(Artifact).where(
                    Artifact.job_id == segment.job_id,
                    Artifact.artifact_type == PROCESSED_ARTIFACT_TYPE,
                )
            ).first()
        data = VideoSegmentResponse.model_validate(segment, from_attributes=True).model_dump()
        data["job"] = JobResponse.model_validate(job, from_attributes=True).model_dump() if job else None
        data["source_artifact"] = (
            VideoSegmentArtifactResponse.model_validate(source_artifact, from_attributes=True).model_dump()
            if source_artifact
            else None
        )
        data["processed_artifact"] = (
            VideoSegmentArtifactResponse.model_validate(processed_artifact, from_attributes=True).model_dump()
            if processed_artifact
            else None
        )
        responses.append(data)
    return responses
