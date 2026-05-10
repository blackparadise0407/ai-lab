from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
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
