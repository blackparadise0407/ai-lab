from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder
from sqlmodel import Session, select

from app.api.job_updates import job_update_broker
from app.api.origins import is_allowed_browser_origin
from app.db.database import get_session
from app.models.entities import Artifact, Job, ProviderRequest

router = APIRouter(prefix="/v1/jobs", tags=["job_events"])


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
            event = await subscription.queue.get()
            await _send_snapshot(websocket, job_id, event)
    except WebSocketDisconnect:
        pass
    finally:
        await job_update_broker.unsubscribe(subscription)
