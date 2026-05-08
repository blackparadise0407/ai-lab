# Self-host Docker Compose

This setup builds separate self-host images for the FastAPI backend and Vite frontend without changing the development Dockerfile at `apps/core/Dockerfile`. The self-host images use multi-stage builds: the backend keeps compiler/build tooling out of the runtime image, and the frontend serves only the compiled Vite `dist/` bundle from nginx.

## Quick start

```bash
cd infra/docker
cp .env.selfhost.example .env.selfhost
# Edit .env.selfhost with your domain, browser origin, and secrets.
docker compose --env-file .env.selfhost -f docker-compose.selfhost.yml up -d --build
```

Open `http://localhost:8080` with the example values. For a real domain, set:

```bash
PUBLIC_API_BASE_URL=https://your-domain.example
ALLOWED_BROWSER_ORIGINS=https://your-domain.example
AI_LAB_SITE_ADDRESS=your-domain.example
HTTP_PORT=80
HTTPS_PORT=443
```

Caddy will route the React app at `/` and proxy backend paths such as `/v1/*`, `/health`, `/swagger`, `/redoc`, and `/openapi.json` to the Core API. Caddy handles WebSocket upgrades automatically for `/v1/jobs/{job_id}/events`.

## Persistence and backups

The Compose file stores SQLite data in the `core-db` volume and uploaded/generated media in the `core-uploads` volume. Back up both volumes before upgrades.

Keep one `core` replica while using SQLite.
