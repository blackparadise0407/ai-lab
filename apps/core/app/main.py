from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from fastapi.responses import RedirectResponse

from app.api.routes import artifacts_router, jobs_router, provider_requests_router
from app.db.database import init_db
from app.workers.video_processor import video_processing_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    video_processing_worker.start()
    yield
    video_processing_worker.stop()


app = FastAPI(
    title="AI Lab Core API",
    version="0.1.0",
    description=(
        "Control-plane API for the dubbing pipeline. "
        "Use Swagger UI to create jobs, upload source videos, and inspect job state."
    ),
    docs_url="/swagger",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


@app.get("/", include_in_schema=False)
def root_redirect_to_docs():
    return RedirectResponse(url="/swagger")


@app.get("/health", summary="Health check")
def healthcheck():
    return {"status": "ok"}


app.include_router(jobs_router)
app.include_router(artifacts_router)
app.include_router(provider_requests_router)
