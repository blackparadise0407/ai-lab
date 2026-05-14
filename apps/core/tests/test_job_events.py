from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.api.job_updates import JobUpdateBroker
from app.api.origins import is_allowed_browser_origin
from app.models.entities import Job, JobStatus


def test_allows_configured_browser_origins() -> None:
    assert is_allowed_browser_origin("http://localhost:5173")
    assert is_allowed_browser_origin("http://127.0.0.1:5173")


def test_rejects_untrusted_browser_origin() -> None:
    assert not is_allowed_browser_origin("https://malicious.example")


def test_rejects_missing_origin() -> None:
    assert not is_allowed_browser_origin(None)


def _create_test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _load_job_events_module():
    module_path = (
        Path(__file__).parents[1] / "app" / "api" / "routes" / "job_events.py"
    )
    spec = importlib.util.spec_from_file_location("job_events_under_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_global_job_update_broker_subscribers_receive_all_job_notifications() -> None:
    async def run_broker_check() -> None:
        broker = JobUpdateBroker()
        subscription = await broker.subscribe_all()
        try:
            broker.notify(123, "job_progress_updated")
            update = await asyncio.wait_for(subscription.queue.get(), timeout=1)
        finally:
            await broker.unsubscribe_all(subscription)

        assert update.job_id == 123
        assert update.event == "job_progress_updated"

    asyncio.run(run_broker_check())


def test_global_job_events_stream_sends_active_snapshot_and_updates(monkeypatch) -> None:
    engine = _create_test_engine()
    base_time = datetime(2026, 1, 1, 12, 0, 0)

    with Session(engine) as session:
        older_active = Job(
            external_job_id="active_older",
            status=JobStatus.CREATED,
            created_at=base_time,
            updated_at=base_time,
        )
        newer_active = Job(
            external_job_id="active_newer",
            status=JobStatus.PROCESSING,
            created_at=base_time + timedelta(minutes=1),
            updated_at=base_time + timedelta(minutes=1),
        )
        completed = Job(
            external_job_id="completed",
            status=JobStatus.COMPLETED,
            created_at=base_time + timedelta(minutes=2),
            updated_at=base_time + timedelta(minutes=2),
        )
        session.add_all([older_active, newer_active, completed])
        session.commit()
        session.refresh(older_active)
        session.refresh(newer_active)
        older_active_id = older_active.id

    def override_get_session():
        with Session(engine) as session:
            yield session

    job_events_module = _load_job_events_module()
    monkeypatch.setattr(job_events_module, "get_session", override_get_session)

    events_app = FastAPI()
    events_app.include_router(job_events_module.router)
    client = TestClient(events_app)
    with client.websocket_connect(
        "/v1/jobs/events", headers={"origin": "http://localhost:5173"}
    ) as websocket:
        snapshot = websocket.receive_json()
        assert snapshot["event"] == "snapshot"
        assert [item["external_job_id"] for item in snapshot["items"]] == [
            "active_newer",
            "active_older",
        ]
        assert snapshot["total"] == 2

        with Session(engine) as session:
            job = session.get(Job, older_active_id)
            assert job is not None
            job.status = JobStatus.COMPLETED
            job.updated_at = base_time + timedelta(minutes=3)
            session.add(job)
            session.commit()

        job_events_module.job_update_broker.notify(older_active_id, "job_completed")
        update = websocket.receive_json()
        assert update["event"] == "job_completed"
        assert update["job_id"] == older_active_id
        assert update["status"] == "completed"
        assert update["job"]["external_job_id"] == "active_older"
