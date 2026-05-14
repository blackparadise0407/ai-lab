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
                "model_name": "small",
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
    assert payload["model_name"] == "small"
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


def test_create_collection_render_combines_completed_segments_in_order(monkeypatch, tmp_path) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    first_output = tmp_path / "first.mp4"
    second_output = tmp_path / "second.mp4"
    first_output.write_bytes(b"first")
    second_output.write_bytes(b"second")
    seen_inputs: list[str] = []

    with Session(engine) as session:
        from app.models.entities import Artifact, Job, JobStatus, VideoCollection, VideoSegment

        collection = VideoCollection(external_collection_id="vc_render_me")
        session.add(collection)
        session.commit()
        session.refresh(collection)
        collection_id = collection.id

        for index, output_file in [(2, second_output), (1, first_output)]:
            job = Job(external_job_id=f"job_render_{index}", status=JobStatus.COMPLETED)
            session.add(job)
            session.commit()
            session.refresh(job)
            artifact = Artifact(
                job_id=job.id,
                artifact_type="processed_video",
                storage_url=str(output_file),
                content_type="video/mp4",
            )
            session.add(artifact)
            session.commit()
            session.refresh(artifact)
            session.add(
                VideoSegment(
                    collection_id=collection_id,
                    job_id=job.id,
                    sequence_index=index,
                    start_seconds=0,
                    end_seconds=5,
                    duration_seconds=5,
                    processed_artifact_id=artifact.id,
                )
            )
            session.commit()

    def fake_combine(input_paths, output_path):
        from app.services.video_combiner import CombinedVideo

        seen_inputs.extend(str(path) for path in input_paths)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"combined")
        return CombinedVideo(path=output_path, duration_seconds=10)

    monkeypatch.setattr("app.api.routes.video_collections.combine_videos", fake_combine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        response = client.post(f"/v1/video-collections/{collection_id}/renders", json={})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["duration_seconds"] == 10
    assert seen_inputs == [str(first_output), str(second_output)]


def test_delete_video_collection_removes_render_files(tmp_path) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    render_file = tmp_path / "combined.mp4"
    render_file.write_bytes(b"combined")

    with Session(engine) as session:
        from app.models.entities import VideoCollection, VideoCollectionRender

        collection = VideoCollection(external_collection_id="vc_render_delete")
        session.add(collection)
        session.commit()
        session.refresh(collection)
        collection_id = collection.id
        session.add(
            VideoCollectionRender(
                collection_id=collection_id,
                output_path=str(render_file),
                included_segment_ids="",
            )
        )
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
    assert not render_file.exists()
    with Session(engine) as session:
        from app.models.entities import VideoCollectionRender

        assert session.exec(select(VideoCollectionRender)).all() == []
