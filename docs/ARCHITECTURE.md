# Architecture (Draft)

## Top-level directories

- `apps/api`: FastAPI service (REST API, auth, job orchestration entrypoints)
- `apps/worker`: Celery worker (transcribe, translate, tts submit, mux)
- `apps/web`: Next.js dashboard (upload, status, artifacts)
- `services/media`: FFmpeg-focused helpers and media pipelines
- `packages/shared/schemas`: shared request/response schemas
- `packages/shared/utils`: shared utility modules
- `infra/docker`: Dockerfiles and compose assets
- `infra/nginx`: reverse proxy config
- `infra/terraform`: cloud infrastructure modules
- `scripts`: local dev and operational scripts
- `docs`: architecture, API contract, runbooks
