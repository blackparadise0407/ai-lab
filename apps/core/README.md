# Core API

FastAPI + SQLite service for the dubbing pipeline control plane.

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Environment

Create `apps/core/.env` for local testing. `app.main` loads this automatically at startup.

```bash
OPENAI_API_KEY=sk-...
OPENAI_TRANSLATION_MODEL=gpt-4.1-mini

# Optional pipeline settings
WHISPER_MODEL=small
WHISPER_COMPUTE_TYPE=int8
DUB_PROVIDER_URL=
```

If `OPENAI_API_KEY` is not set, subtitle translation falls back to a passthrough mock mode.

`target_language` is taken from the job record (`Job.target_language`) instead of environment configuration.
