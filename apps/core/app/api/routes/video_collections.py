from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.job_updates import job_update_broker
from app.db.database import get_session
from app.models.entities import Artifact, ConnectedAccount, Job, JobStatus, VideoCollection, VideoCollectionRender, VideoSegment
from app.schemas.jobs import JobResponse
from app.schemas.video_collections import (
    VideoCollectionCreateRequest,
    VideoCollectionDetailResponse,
    VideoCollectionListResponse,
    VideoCollectionRenderCreateRequest,
    VideoCollectionRenderListResponse,
    VideoCollectionRenderPublishRequest,
    VideoCollectionRenderResponse,
    VideoCollectionResponse,
    VideoSegmentArtifactResponse,
    VideoSegmentResponse,
)
from app.services.deletion import delete_collection_and_artifacts
from app.services.video_collections import refresh_collection_rollup
from app.services.video_combiner import VideoCombineError, combine_videos
from app.services.video_splitter import VideoSplitError, split_video
from app.providers.upload_provider import UploadCredentials, UploadProviderClient, UploadProviderError, UploadRequest
from app.workers.video_processor import (
    SOURCE_VIDEO_ARTIFACT_TYPE,
    PROCESSED_ARTIFACT_TYPE,
    video_processing_worker,
)

router = APIRouter(prefix="/v1/video-collections", tags=["video_collections"])

COLLECTION_UPLOADS_DIR = Path("uploads/source_videos")
COLLECTION_SEGMENTS_DIR = Path("uploads/source_segments")
COLLECTION_RENDERS_DIR = Path("uploads/collection_renders")

upload_provider_client = UploadProviderClient()


@router.post(
    "",
    response_model=VideoCollectionResponse,
    status_code=201,
    summary="Create a video collection",
)
def create_video_collection(
    payload: VideoCollectionCreateRequest,
    session: Session = Depends(get_session),
):
    collection = VideoCollection(
        external_collection_id=f"vc_{uuid4().hex[:12]}",
        title=payload.title,
        source_language=payload.source_language,
        target_language=payload.target_language,
        model_name=payload.model_name,
        translation_context=payload.translation_context,
        voice_id=payload.voice_id,
        output_video_speed=payload.output_video_speed,
        original_audio_volume=payload.original_audio_volume,
        split_threshold_seconds=payload.split_threshold_seconds,
    )
    session.add(collection)
    session.commit()
    session.refresh(collection)
    return collection


@router.get(
    "", response_model=VideoCollectionListResponse, summary="List video collections"
)
def list_video_collections(
    status: JobStatus | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    count_statement = select(func.count(VideoCollection.id))
    statement = (
        select(VideoCollection)
        .order_by(VideoCollection.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if status is not None:
        count_statement = count_statement.where(VideoCollection.status == status)
        statement = statement.where(VideoCollection.status == status)

    total = session.exec(count_statement).one()
    collections = list(session.exec(statement).all())
    items = [
        refresh_collection_rollup(session, collection) for collection in collections
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/{collection_id}",
    response_model=VideoCollectionDetailResponse,
    summary="Get video collection details",
)
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
    existing_segment = session.exec(
        select(VideoSegment).where(VideoSegment.collection_id == collection.id)
    ).first()
    if existing_segment:
        raise HTTPException(
            status_code=409, detail="Collection already has source video segments"
        )

    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="Only video files are supported")

    extension = Path(file.filename or "video").suffix or ".mp4"
    upload_path = (
        COLLECTION_UPLOADS_DIR
        / f"collection_{collection_id}_{uuid4().hex[:8]}{extension}"
    )
    upload_path.parent.mkdir(parents=True, exist_ok=True)

    with upload_path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            output.write(chunk)

    segment_output_dir = (
        COLLECTION_SEGMENTS_DIR / f"collection_{collection_id}_{uuid4().hex[:8]}"
    )
    try:
        split_segments = await run_in_threadpool(
            split_video,
            upload_path,
            segment_output_dir,
            max_segment_seconds=collection.split_threshold_seconds,
        )
    except VideoSplitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(timezone.utc)
    collection.original_filename = file.filename
    collection.total_duration_seconds = max(
        segment.end_seconds for segment in split_segments
    )
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
            model_name=collection.model_name,
            translation_context=collection.translation_context,
            voice_id=collection.voice_id,
            output_video_speed=collection.output_video_speed,
            original_audio_volume=collection.original_audio_volume,
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
    "/{collection_id}/renders",
    response_model=VideoCollectionRenderListResponse,
    summary="List combined renders for a video collection",
)
def list_video_collection_renders(
    collection_id: int, session: Session = Depends(get_session)
):
    _get_collection_or_404(session, collection_id)
    renders = list(
        session.exec(
            select(VideoCollectionRender)
            .where(VideoCollectionRender.collection_id == collection_id)
            .order_by(VideoCollectionRender.created_at.desc())
        ).all()
    )
    return {"items": [_render_response(render) for render in renders]}


@router.post(
    "/{collection_id}/renders",
    response_model=VideoCollectionRenderResponse,
    status_code=201,
    summary="Combine processed collection segments into one long video",
)
def create_video_collection_render(
    collection_id: int,
    payload: VideoCollectionRenderCreateRequest,
    session: Session = Depends(get_session),
):
    collection = _get_collection_or_404(session, collection_id)
    refresh_collection_rollup(session, collection)
    selected_segments = _select_render_segments(session, collection_id, payload.segment_ids)

    render = VideoCollectionRender(
        collection_id=collection_id,
        status=JobStatus.PROCESSING,
        current_step="combining_segments",
        progress_percent=25,
        included_segment_ids=",".join(str(segment.id) for segment, _ in selected_segments),
    )
    session.add(render)
    session.commit()
    session.refresh(render)

    output_path = COLLECTION_RENDERS_DIR / f"collection_{collection_id}" / f"render_{render.id}_{uuid4().hex[:8]}.mp4"
    try:
        combined = combine_videos([Path(artifact.storage_url) for _, artifact in selected_segments], output_path)
    except VideoCombineError as exc:
        render.status = JobStatus.FAILED
        render.current_step = "combine_failed"
        render.progress_percent = 100
        render.error_message = str(exc)
        render.updated_at = datetime.now(timezone.utc)
        session.add(render)
        session.commit()
        session.refresh(render)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    render.status = JobStatus.COMPLETED
    render.current_step = "combined_video_ready"
    render.progress_percent = 100
    render.output_path = str(combined.path)
    render.duration_seconds = combined.duration_seconds
    render.updated_at = datetime.now(timezone.utc)
    session.add(render)
    session.commit()
    session.refresh(render)
    return _render_response(render)


@router.get(
    "/{collection_id}/renders/{render_id}",
    response_model=VideoCollectionRenderResponse,
    summary="Get a combined collection render",
)
def get_video_collection_render(
    collection_id: int, render_id: int, session: Session = Depends(get_session)
):
    render = _get_render_or_404(session, collection_id, render_id)
    return _render_response(render)


@router.get(
    "/{collection_id}/renders/{render_id}/preview",
    summary="Preview a combined collection render",
)
def preview_video_collection_render(
    collection_id: int,
    render_id: int,
    range_header: str | None = Header(default=None, alias="Range"),
    session: Session = Depends(get_session),
):
    render = _get_render_or_404(session, collection_id, render_id)
    render_path = _render_output_path_or_404(render)
    return _video_file_response(render_path, render.content_type, range_header, inline=True)


@router.get(
    "/{collection_id}/renders/{render_id}/download",
    summary="Download a combined collection render",
)
def download_video_collection_render(
    collection_id: int, render_id: int, session: Session = Depends(get_session)
):
    render = _get_render_or_404(session, collection_id, render_id)
    render_path = _render_output_path_or_404(render)
    return FileResponse(
        path=render_path,
        media_type=render.content_type,
        filename=render_path.name,
        content_disposition_type="attachment",
    )


@router.post(
    "/{collection_id}/renders/{render_id}/uploads",
    response_model=VideoCollectionRenderResponse,
    summary="Publish a combined collection render",
)
def publish_video_collection_render(
    collection_id: int,
    render_id: int,
    payload: VideoCollectionRenderPublishRequest,
    session: Session = Depends(get_session),
):
    render = _get_render_or_404(session, collection_id, render_id)
    if render.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Render must be completed before publishing")

    render_path = _render_output_path_or_404(render)
    try:
        result = upload_provider_client.upload(
            payload.platform,
            UploadRequest(
                job_id=-(render.id or 0),
                video_path=render_path,
                title=payload.title,
                description=payload.description,
                privacy=payload.privacy,
            ),
            credentials=_get_upload_credentials(session, payload),
        )
    except UploadProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    render.published_platform = result.platform
    render.provider_request_id = result.provider_request_id
    render.remote_url = result.remote_url
    render.updated_at = datetime.now(timezone.utc)
    session.add(render)
    session.commit()
    session.refresh(render)
    return _render_response(render)


@router.delete(
    "/{collection_id}",
    status_code=204,
    summary="Delete video collection",
    description="Deletes a video collection, all segment jobs, database artifact records, and local artifact files.",
)
def delete_video_collection(
    collection_id: int, session: Session = Depends(get_session)
):
    collection = _get_collection_or_404(session, collection_id)
    delete_collection_and_artifacts(session, collection)
    return None


@router.get(
    "/{collection_id}/segments",
    response_model=list[VideoSegmentResponse],
    summary="List segments for a video collection",
)
def list_video_collection_segments(
    collection_id: int, session: Session = Depends(get_session)
):
    collection = _get_collection_or_404(session, collection_id)
    refresh_collection_rollup(session, collection)
    return _segment_responses(session, collection.id)


def _get_collection_or_404(session: Session, collection_id: int) -> VideoCollection:
    collection = session.exec(
        select(VideoCollection).where(VideoCollection.id == collection_id)
    ).first()
    if not collection:
        raise HTTPException(status_code=404, detail="Video collection not found")
    return collection


def _collection_detail_response(session: Session, collection: VideoCollection) -> dict:
    data = VideoCollectionResponse.model_validate(
        collection, from_attributes=True
    ).model_dump()
    data["segments"] = _segment_responses(session, collection.id)
    return data


def _segment_responses(session: Session, collection_id: int) -> list[dict]:
    segments = list(
        session.exec(
            select(VideoSegment)
            .where(VideoSegment.collection_id == collection_id)
            .order_by(VideoSegment.sequence_index)
        ).all()
    )
    responses: list[dict] = []
    for segment in segments:
        job = session.get(Job, segment.job_id)
        source_artifact = (
            session.get(Artifact, segment.source_artifact_id)
            if segment.source_artifact_id
            else None
        )
        processed_artifact = (
            session.get(Artifact, segment.processed_artifact_id)
            if segment.processed_artifact_id
            else None
        )
        if processed_artifact is None:
            processed_artifact = session.exec(
                select(Artifact).where(
                    Artifact.job_id == segment.job_id,
                    Artifact.artifact_type == PROCESSED_ARTIFACT_TYPE,
                )
            ).first()
        data = VideoSegmentResponse.model_validate(
            segment, from_attributes=True
        ).model_dump()
        data["job"] = (
            JobResponse.model_validate(job, from_attributes=True).model_dump()
            if job
            else None
        )
        data["source_artifact"] = (
            VideoSegmentArtifactResponse.model_validate(
                source_artifact, from_attributes=True
            ).model_dump()
            if source_artifact
            else None
        )
        data["processed_artifact"] = (
            VideoSegmentArtifactResponse.model_validate(
                processed_artifact, from_attributes=True
            ).model_dump()
            if processed_artifact
            else None
        )
        responses.append(data)
    return responses


def _select_render_segments(
    session: Session, collection_id: int, segment_ids: list[int]
) -> list[tuple[VideoSegment, Artifact]]:
    statement = (
        select(VideoSegment)
        .where(VideoSegment.collection_id == collection_id)
        .order_by(VideoSegment.sequence_index)
    )
    segments = list(session.exec(statement).all())
    if segment_ids:
        requested_ids = set(segment_ids)
        segments = [segment for segment in segments if segment.id in requested_ids]
        found_ids = {segment.id for segment in segments}
        missing_ids = requested_ids - found_ids
        if missing_ids:
            raise HTTPException(
                status_code=400,
                detail="Selected segments must belong to the requested collection",
            )

    selected: list[tuple[VideoSegment, Artifact]] = []
    for segment in segments:
        job = session.get(Job, segment.job_id)
        if not job or job.status != JobStatus.COMPLETED:
            continue
        artifact = None
        if segment.processed_artifact_id:
            artifact = session.get(Artifact, segment.processed_artifact_id)
        if artifact is None:
            artifact = session.exec(
                select(Artifact).where(
                    Artifact.job_id == segment.job_id,
                    Artifact.artifact_type == PROCESSED_ARTIFACT_TYPE,
                )
            ).first()
        if artifact:
            selected.append((segment, artifact))

    if not selected:
        raise HTTPException(
            status_code=409,
            detail="Collection has no completed processed segments to combine",
        )
    return selected


def _get_render_or_404(
    session: Session, collection_id: int, render_id: int
) -> VideoCollectionRender:
    render = session.exec(
        select(VideoCollectionRender).where(
            VideoCollectionRender.id == render_id,
            VideoCollectionRender.collection_id == collection_id,
        )
    ).first()
    if not render:
        raise HTTPException(status_code=404, detail="Collection render not found")
    return render


def _render_output_path_or_404(render: VideoCollectionRender) -> Path:
    if not render.output_path:
        raise HTTPException(status_code=404, detail="Render output is not available")
    render_path = Path(render.output_path)
    if not render_path.is_file():
        raise HTTPException(status_code=404, detail="Render output file not found")
    return render_path


def _render_response(render: VideoCollectionRender) -> dict:
    return {
        "id": render.id,
        "collection_id": render.collection_id,
        "status": render.status,
        "current_step": render.current_step,
        "progress_percent": render.progress_percent,
        "included_segment_ids": [
            int(value)
            for value in render.included_segment_ids.split(",")
            if value.strip().isdigit()
        ],
        "output_path": render.output_path,
        "content_type": render.content_type,
        "duration_seconds": render.duration_seconds,
        "error_message": render.error_message,
        "published_platform": render.published_platform,
        "provider_request_id": render.provider_request_id,
        "remote_url": render.remote_url,
        "created_at": render.created_at,
        "updated_at": render.updated_at,
    }


def _video_file_response(
    path: Path,
    media_type: str,
    range_header: str | None,
    *,
    inline: bool,
):
    if range_header is None:
        return FileResponse(
            path=path,
            media_type=media_type,
            filename=path.name,
            content_disposition_type="inline" if inline else "attachment",
            headers={"Accept-Ranges": "bytes"},
        )

    file_size = path.stat().st_size
    byte_range = _parse_byte_range(range_header, file_size)
    if byte_range is None:
        return StreamingResponse(
            iter(()),
            status_code=416,
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
        _iter_file_range(path, start, end),
        status_code=206,
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


def _iter_file_range(path: Path, start: int, end: int):
    with path.open("rb") as video_file:
        video_file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = video_file.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _get_upload_credentials(
    session: Session,
    payload: VideoCollectionRenderPublishRequest,
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
        token_uri=os.getenv("YOUTUBE_TOKEN_URI", "https://oauth2.googleapis.com/token")
        if platform == "youtube"
        else None,
        client_id=os.getenv("YOUTUBE_CLIENT_ID") if platform == "youtube" else None,
        client_secret=os.getenv("YOUTUBE_CLIENT_SECRET")
        if platform == "youtube"
        else None,
        scopes=scopes,
    )
