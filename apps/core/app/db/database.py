import os

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

# Ensure SQLModel metadata is populated before create_all.
from app.models.entities import (  # noqa: F401
    Artifact,
    ConnectedAccount,
    ConnectorState,
    Job,
    ProviderRequest,
    VideoCollection,
    VideoCollectionRender,
    VideoSegment,
)

DATABASE_URL = os.getenv("CORE_DATABASE_URL", "sqlite:///./core.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    inspector = inspect(engine)
    table_columns = {
        table_name: {column["name"] for column in inspector.get_columns(table_name)}
        for table_name in inspector.get_table_names()
    }
    alter_statements = []
    if "job" in table_columns and "model_name" not in table_columns["job"]:
        alter_statements.append(
            "ALTER TABLE job ADD COLUMN model_name VARCHAR(32) NOT NULL DEFAULT 'medium'"
        )
    if "job" in table_columns and "translation_context" not in table_columns["job"]:
        alter_statements.append(
            "ALTER TABLE job ADD COLUMN translation_context VARCHAR(100)"
        )
    if "job" in table_columns and "voice_id" not in table_columns["job"]:
        alter_statements.append("ALTER TABLE job ADD COLUMN voice_id VARCHAR(128)")
    if "job" in table_columns and "output_video_speed" not in table_columns["job"]:
        alter_statements.append(
            "ALTER TABLE job ADD COLUMN output_video_speed FLOAT NOT NULL DEFAULT 1.0"
        )
    if "job" in table_columns and "original_audio_volume" not in table_columns["job"]:
        alter_statements.append(
            "ALTER TABLE job ADD COLUMN original_audio_volume FLOAT NOT NULL DEFAULT 0.15"
        )
    if (
        "videocollection" in table_columns
        and "model_name" not in table_columns["videocollection"]
    ):
        alter_statements.append(
            "ALTER TABLE videocollection ADD COLUMN model_name VARCHAR(32) NOT NULL DEFAULT 'medium'"
        )
    if (
        "videocollection" in table_columns
        and "translation_context" not in table_columns["videocollection"]
    ):
        alter_statements.append(
            "ALTER TABLE videocollection ADD COLUMN translation_context VARCHAR(100)"
        )
    if (
        "videocollection" in table_columns
        and "voice_id" not in table_columns["videocollection"]
    ):
        alter_statements.append(
            "ALTER TABLE videocollection ADD COLUMN voice_id VARCHAR(128)"
        )
    if (
        "videocollection" in table_columns
        and "output_video_speed" not in table_columns["videocollection"]
    ):
        alter_statements.append(
            "ALTER TABLE videocollection ADD COLUMN output_video_speed FLOAT NOT NULL DEFAULT 1.0"
        )
    if (
        "videocollection" in table_columns
        and "original_audio_volume" not in table_columns["videocollection"]
    ):
        alter_statements.append(
            "ALTER TABLE videocollection ADD COLUMN original_audio_volume FLOAT NOT NULL DEFAULT 0.15"
        )

    if not alter_statements:
        return

    with engine.begin() as connection:
        for statement in alter_statements:
            connection.execute(text(statement))


def get_session():
    with Session(engine) as session:
        yield session
