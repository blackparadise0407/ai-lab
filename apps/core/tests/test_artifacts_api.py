from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.db.database import get_session
from app.models.entities import Artifact, Job


_ARTIFACTS_ROUTE_PATH = Path(__file__).parents[1] / "app/api/routes/artifacts.py"
_ARTIFACTS_ROUTE_SPEC = spec_from_file_location(
    "artifacts_route_module", _ARTIFACTS_ROUTE_PATH
)
assert _ARTIFACTS_ROUTE_SPEC is not None and _ARTIFACTS_ROUTE_SPEC.loader is not None
artifacts_route_module = module_from_spec(_ARTIFACTS_ROUTE_SPEC)
_ARTIFACTS_ROUTE_SPEC.loader.exec_module(artifacts_route_module)

app = FastAPI()
app.include_router(artifacts_route_module.router)


def _client_with_artifact(
    tmp_path: Path, *, file_name: str, content: bytes, content_type: str
):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    artifact_file = tmp_path / file_name
    artifact_file.write_bytes(content)

    with Session(engine) as session:
        job = Job(external_job_id=f"job_{file_name}")
        session.add(job)
        session.commit()
        session.refresh(job)

        artifact = Artifact(
            job_id=job.id,
            artifact_type=(
                "processed_video"
                if content_type.startswith("video/")
                else "transcript"
            ),
            storage_url=str(artifact_file),
            content_type=content_type,
        )
        session.add(artifact)
        session.commit()
        session.refresh(artifact)
        artifact_id = artifact.id

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), artifact_id


def test_preview_video_artifact_supports_partial_content(tmp_path) -> None:
    client, artifact_id = _client_with_artifact(
        tmp_path,
        file_name="preview.mp4",
        content=b"0123456789",
        content_type="video/mp4",
    )

    try:
        response = client.get(
            f"/v1/artifacts/{artifact_id}/preview",
            headers={"Range": "bytes=2-5"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"
    assert response.headers["content-type"].startswith("video/mp4")


def test_preview_video_artifact_supports_suffix_range(tmp_path) -> None:
    client, artifact_id = _client_with_artifact(
        tmp_path,
        file_name="preview.mp4",
        content=b"0123456789",
        content_type="video/mp4",
    )

    try:
        response = client.get(
            f"/v1/artifacts/{artifact_id}/preview",
            headers={"Range": "bytes=-4"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 206
    assert response.content == b"6789"
    assert response.headers["content-range"] == "bytes 6-9/10"


def test_preview_video_artifact_rejects_unsatisfiable_range(tmp_path) -> None:
    client, artifact_id = _client_with_artifact(
        tmp_path,
        file_name="preview.mp4",
        content=b"0123456789",
        content_type="video/mp4",
    )

    try:
        response = client.get(
            f"/v1/artifacts/{artifact_id}/preview",
            headers={"Range": "bytes=99-100"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 416
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes */10"


def test_preview_non_video_artifact_returns_inline_static_file(tmp_path) -> None:
    client, artifact_id = _client_with_artifact(
        tmp_path,
        file_name="transcript.txt",
        content=b"hello transcript",
        content_type="text/plain",
    )

    try:
        response = client.get(f"/v1/artifacts/{artifact_id}/preview")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content == b"hello transcript"
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"].startswith("inline")
