from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.db.database import get_session
from app.main import app


def test_create_video_collection_stores_translation_context() -> None:
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
            "/v1/video-collections",
            json={
                "title": "Long source",
                "source_language": "zh",
                "target_language": "vi",
                "translation_context": "formal product demo",
                "voice_id": "voice-one",
                "output_video_speed": 1.5,
                "original_audio_volume": 0.25,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    payload = response.json()
    assert payload["translation_context"] == "formal product demo"
    assert payload["output_video_speed"] == 1.5
    assert payload["original_audio_volume"] == 0.25


def test_delete_video_collection_removes_segment_jobs_and_local_files(tmp_path) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    source_file = tmp_path / "segment-source.mp4"
    output_file = tmp_path / "segment-output.mp4"
    source_file.write_bytes(b"source")
    output_file.write_bytes(b"output")

    with Session(engine) as session:
        from app.models.entities import Artifact, Job, VideoCollection, VideoSegment

        collection = VideoCollection(external_collection_id="vc_delete_me")
        session.add(collection)
        session.commit()
        session.refresh(collection)
        collection_id = collection.id

        job = Job(external_job_id="job_delete_me")
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

        source_artifact = Artifact(
            job_id=job_id,
            artifact_type="source_video",
            storage_url=str(source_file),
            content_type="video/mp4",
        )
        processed_artifact = Artifact(
            job_id=job_id,
            artifact_type="processed_video",
            storage_url=str(output_file),
            content_type="video/mp4",
        )
        session.add(source_artifact)
        session.add(processed_artifact)
        session.commit()
        session.refresh(source_artifact)
        session.refresh(processed_artifact)

        collection.source_artifact_id = source_artifact.id
        segment = VideoSegment(
            collection_id=collection_id,
            job_id=job_id,
            sequence_index=1,
            start_seconds=0,
            end_seconds=5,
            duration_seconds=5,
            source_artifact_id=source_artifact.id,
            processed_artifact_id=processed_artifact.id,
        )
        session.add(collection)
        session.add(segment)
        session.commit()

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        response = client.delete(f"/v1/video-collections/{collection_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert not source_file.exists()
    assert not output_file.exists()
    with Session(engine) as session:
        from app.models.entities import Artifact, Job, VideoCollection, VideoSegment

        assert session.get(VideoCollection, collection_id) is None
        assert session.get(Job, job_id) is None
        assert session.exec(select(VideoSegment)).all() == []
        assert session.exec(select(Artifact)).all() == []
