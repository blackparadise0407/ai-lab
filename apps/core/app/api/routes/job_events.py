from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder
from sqlmodel import Session, select

from app.api.job_updates import job_update_broker
from app.api.origins import is_allowed_browser_origin
from app.db.database import get_session
from app.models.entities import Artifact, Job, JobStatus, ProviderRequest

router = APIRouter(prefix="/v1/jobs", tags=["job_events"])

ACTIVE_JOB_STATUSES = (
    JobStatus.CREATED,
    JobStatus.UPLOADED,
    JobStatus.PROCESSING,
    JobStatus.WAITING_PROVIDER,
    JobStatus.FINALIZING,
)


def _active_jobs_snapshot(session: Session) -> dict:
    jobs = list(
        session.exec(
            select(Job)
            .where(Job.status.in_(ACTIVE_JOB_STATUSES))
            .order_by(Job.created_at.desc())
        ).all()
    )
    return jsonable_encoder(
        {
            "items": jobs,
            "total": len(jobs),
            "limit": len(jobs),
            "offset": 0,
        }
    )


def _job_list_event(job_id: int, session: Session) -> dict | None:
    job = session.exec(select(Job).where(Job.id == job_id)).first()
    if not job:
        return None

    return jsonable_encoder(
        {
            "job": job,
            "job_id": job.id,
            "status": job.status,
            "updated_at": job.updated_at,
        }
    )


def _job_snapshot(job_id: int, session: Session) -> dict | None:
    job = session.exec(select(Job).where(Job.id == job_id)).first()
    if not job:
        return None

    artifacts = list(session.exec(select(Artifact).where(Artifact.job_id == job_id)).all())
    provider_requests = list(
        session.exec(select(ProviderRequest).where(ProviderRequest.job_id == job_id)).all()
    )
    return jsonable_encoder(
        {
            "job": job,
            "artifacts": artifacts,
            "provider_requests": provider_requests,
        }
    )


async def _send_snapshot(websocket: WebSocket, job_id: int, event: str) -> bool:
    session_generator = get_session()
    session = next(session_generator)
    try:
        snapshot = _job_snapshot(job_id, session)
    finally:
        session_generator.close()

    if snapshot is None:
        await websocket.send_json({"event": "job_not_found", "job_id": job_id})
        return False

    await websocket.send_json({"event": event, **snapshot})
    return True


async def _send_active_jobs_snapshot(websocket: WebSocket) -> None:
    session_generator = get_session()
    session = next(session_generator)
    try:
        snapshot = _active_jobs_snapshot(session)
    finally:
        session_generator.close()

    await websocket.send_json({"event": "snapshot", **snapshot})


async def _send_job_list_event(websocket: WebSocket, job_id: int, event: str) -> None:
    session_generator = get_session()
    session = next(session_generator)
    try:
        snapshot = _job_list_event(job_id, session)
    finally:
        session_generator.close()

    if snapshot is None:
        await websocket.send_json({"event": "job_deleted", "job_id": job_id})
        return

    await websocket.send_json({"event": event, **snapshot})


@router.websocket("/events")
async def stream_all_job_events(websocket: WebSocket):
    if not is_allowed_browser_origin(websocket.headers.get("origin")):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    await _send_active_jobs_snapshot(websocket)

    subscription = await job_update_broker.subscribe_all()
    try:
        while True:
            update = await subscription.queue.get()
            await _send_job_list_event(websocket, update.job_id, update.event)
    except WebSocketDisconnect:
        pass
    finally:
        await job_update_broker.unsubscribe_all(subscription)


@router.websocket("/{job_id}/events")
async def stream_job_events(websocket: WebSocket, job_id: int):
    if not is_allowed_browser_origin(websocket.headers.get("origin")):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    has_snapshot = await _send_snapshot(websocket, job_id, "snapshot")
    if not has_snapshot:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    subscription = await job_update_broker.subscribe(job_id)
    try:
        while True:
            update = await subscription.queue.get()
            await _send_snapshot(websocket, job_id, update.event)
    except WebSocketDisconnect:
        pass
    finally:
        await job_update_broker.unsubscribe(subscription)
