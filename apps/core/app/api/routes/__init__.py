from app.api.routes.artifacts import router as artifacts_router
from app.api.routes.connectors import router as connectors_router
from app.api.routes.dub_provider import router as dub_provider_router
from app.api.routes.job_events import router as job_events_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.provider_requests import router as provider_requests_router
from app.api.routes.uploads import router as uploads_router
from app.api.routes.video_collections import router as video_collections_router

__all__ = [
    "connectors_router",
    "dub_provider_router",
    "jobs_router",
    "artifacts_router",
    "provider_requests_router",
    "job_events_router",
    "uploads_router",
    "video_collections_router",
]
