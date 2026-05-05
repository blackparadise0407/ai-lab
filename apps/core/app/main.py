from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager

from app.api.routes import artifacts_router, jobs_router, provider_requests_router
from app.db.database import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="AI Lab Core API", version="0.1.0", lifespan=lifespan)

@app.get("/health")
def healthcheck():
    return {"status": "ok"}

app.include_router(jobs_router)
app.include_router(artifacts_router)
app.include_router(provider_requests_router)
