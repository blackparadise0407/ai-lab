from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.db.database import get_session
from app.main import app
from app.models.entities import Job, JobStatus


def test_list_jobs_supports_status_filter_and_pagination() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    base_time = datetime(2026, 1, 1, 12, 0, 0)
    with Session(engine) as session:
        for index in range(4):
            session.add(
                Job(
                    external_job_id=f"completed_{index}",
                    status=JobStatus.COMPLETED,
                    updated_at=base_time + timedelta(minutes=index),
                )
            )
        session.add(
            Job(
                external_job_id="processing_0",
                status=JobStatus.PROCESSING,
                updated_at=base_time + timedelta(minutes=10),
            )
        )
        session.commit()

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        response = client.get("/v1/jobs", params={"status": "completed", "limit": 2, "offset": 1})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 4
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert [item["external_job_id"] for item in payload["items"]] == [
        "completed_2",
        "completed_1",
    ]


def test_create_job_accepts_voice_id() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/jobs",
            json={
                "source_language": "zh",
                "target_language": "vi",
                "voice_id": "voice-one",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["voice_id"] == "voice-one"
