from fastapi import FastAPI

from app.api.routes import artifacts_router, jobs_router, provider_requests_router
from app.db.database import init_db

app = FastAPI(title="AI Lab Core API", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


app.include_router(jobs_router)
app.include_router(artifacts_router)
app.include_router(provider_requests_router)
