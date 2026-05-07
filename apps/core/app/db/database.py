from sqlmodel import Session, SQLModel, create_engine

# Ensure SQLModel metadata is populated before create_all.
from app.models.entities import (  # noqa: F401
    Artifact,
    ConnectedAccount,
    ConnectorState,
    Job,
    ProviderRequest,
    VideoCollection,
    VideoSegment,
)

SQLITE_URL = "sqlite:///./core.db"
engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
