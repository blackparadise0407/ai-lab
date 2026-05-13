from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.db.database import get_session
from app.main import app
from app.models.entities import Artifact, Job, JobStatus


def test_list_jobs_sorts_by_created_time_and_supports_status_filter_and_pagination() -> None:
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
                    created_at=base_time + timedelta(minutes=index),
                    updated_at=base_time + timedelta(minutes=10 - index),
                )
            )
        session.add(
            Job(
                external_job_id="processing_0",
                status=JobStatus.PROCESSING,
                created_at=base_time + timedelta(minutes=10),
                updated_at=base_time + timedelta(minutes=20),
            )
        )
        session.commit()

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        response = client.get(
            "/v1/jobs", params={"status": "completed", "limit": 2, "offset": 1}
        )
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


def test_list_jobs_supports_language_and_current_step_filters() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    base_time = datetime(2026, 1, 1, 12, 0, 0)
    with Session(engine) as session:
        session.add_all(
            [
                Job(
                    external_job_id="matching_newer",
                    status=JobStatus.PROCESSING,
                    source_language="zh",
                    target_language="vi-VN",
                    current_step="transcribing_source",
                    created_at=base_time + timedelta(minutes=3),
                ),
                Job(
                    external_job_id="matching_older",
                    status=JobStatus.PROCESSING,
                    source_language="zh",
                    target_language="vi-VN",
                    current_step="transcribing_source",
                    created_at=base_time + timedelta(minutes=1),
                ),
                Job(
                    external_job_id="wrong_source",
                    status=JobStatus.PROCESSING,
                    source_language="en",
                    target_language="vi-VN",
                    current_step="transcribing_source",
                    created_at=base_time + timedelta(minutes=4),
                ),
                Job(
                    external_job_id="wrong_target",
                    status=JobStatus.PROCESSING,
                    source_language="zh",
                    target_language="en-US",
                    current_step="transcribing_source",
                    created_at=base_time + timedelta(minutes=5),
                ),
                Job(
                    external_job_id="wrong_step",
                    status=JobStatus.PROCESSING,
                    source_language="zh",
                    target_language="vi-VN",
                    current_step="translating",
                    created_at=base_time + timedelta(minutes=6),
                ),
            ]
        )
        session.commit()

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        response = client.get(
            "/v1/jobs",
            params={
                "source_language": "zh",
                "target_language": "vi-VN",
                "current_step": "transcribing_source",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert [item["external_job_id"] for item in payload["items"]] == [
        "matching_newer",
        "matching_older",
    ]


def test_create_job_accepts_translation_context() -> None:
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
                "translation_context": "martial arts comedy",
                "voice_id": "voice-one",
                "output_video_speed": 1.25,
                "original_audio_volume": 0.2,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["translation_context"] == "martial arts comedy"
    assert response.json()["voice_id"] == "voice-one"
    assert response.json()["output_video_speed"] == 1.25
    assert response.json()["original_audio_volume"] == 0.2


def test_create_job_rejects_translation_context_over_100_characters() -> None:
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
                "translation_context": "x" * 101,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_retry_failed_job_requeues_existing_source_video(tmp_path, monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")

    with Session(engine) as session:
        job = Job(
            external_job_id="failed_0",
            status=JobStatus.FAILED,
            current_step="translating",
            progress_percent=45,
            error_code="pipeline_error",
            error_message="boom",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="source_video",
                storage_url=str(source_video),
                content_type="video/mp4",
            )
        )
        session.commit()

    enqueued_job_ids: list[int] = []
    monkeypatch.setattr(
        "app.api.routes.jobs.video_processing_worker.enqueue",
        lambda job_id, retry_from_step=None: enqueued_job_ids.append(
            (job_id, retry_from_step)
        ),
    )

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        response = client.post(f"/v1/jobs/{job_id}/retry")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "uploaded"
    assert payload["current_step"] == "retry_queued"
    assert payload["progress_percent"] == 45
    assert payload["error_code"] is None
    assert payload["error_message"] is None
    assert enqueued_job_ids == [(job_id, "translating")]


def test_retry_rejects_non_failed_job(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        job = Job(external_job_id="processing_1", status=JobStatus.PROCESSING)
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    enqueued_job_ids: list[int] = []
    monkeypatch.setattr(
        "app.api.routes.jobs.video_processing_worker.enqueue",
        lambda job_id, retry_from_step=None: enqueued_job_ids.append(
            (job_id, retry_from_step)
        ),
    )

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        response = client.post(f"/v1/jobs/{job_id}/retry")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == "Only failed jobs can be retried"
    assert enqueued_job_ids == []


def test_delete_job_removes_artifacts_provider_requests_and_local_files(tmp_path) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    artifact_file = tmp_path / "job-output.mp4"
    artifact_file.write_bytes(b"video")

    with Session(engine) as session:
        job = Job(external_job_id="delete_me")
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="processed_video",
                storage_url=str(artifact_file),
                content_type="video/mp4",
            )
        )
        from app.models.entities import ProviderRequest

        session.add(
            ProviderRequest(
                job_id=job_id,
                provider_name="upload_youtube",
                provider_request_id="upload_delete_me",
            )
        )
        session.commit()

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        response = client.delete(f"/v1/jobs/{job_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert not artifact_file.exists()
    with Session(engine) as session:
        from app.models.entities import ProviderRequest

        assert session.get(Job, job_id) is None
        assert session.exec(select(Artifact).where(Artifact.job_id == job_id)).all() == []
        assert (
            session.exec(
                select(ProviderRequest).where(ProviderRequest.job_id == job_id)
            ).all()
            == []
        )


def test_cancel_in_progress_job_marks_canceled(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        job = Job(
            external_job_id="processing_cancel",
            status=JobStatus.PROCESSING,
            current_step="transcribing_source",
            progress_percent=25,
            error_code="old_error",
            error_message="old message",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    notifications: list[tuple[int, str]] = []
    monkeypatch.setattr(
        "app.api.routes.jobs.job_update_broker.notify",
        lambda job_id, event_type: notifications.append((job_id, event_type)),
    )

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        response = client.post(f"/v1/jobs/{job_id}/cancel")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "canceled"
    assert payload["current_step"] == "canceled"
    assert payload["progress_percent"] == 25
    assert payload["error_code"] is None
    assert payload["error_message"] is None
    assert notifications == [(job_id, "job_canceled")]


def test_cancel_rejects_completed_job() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        job = Job(external_job_id="completed_cancel", status=JobStatus.COMPLETED)
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        response = client.post(f"/v1/jobs/{job_id}/cancel")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "Only queued or in-progress jobs can be canceled"
    )
