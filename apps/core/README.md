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

DUB_TTS_CHUNK_BATCH_SIZE=5
DUB_PROVIDER_VOICE_CODE=hn_female_ngochuyen_full_48k-fhg
DUB_PROVIDER_URL=https://vbee.vn/api/v1/tts
DUB_PROVIDER_APP_ID=
DUB_PROVIDER_TOKEN=
```

If `OPENAI_API_KEY` is not set, subtitle translation falls back to a passthrough mock mode.

If `DUB_PROVIDER_URL` is not set, TTS synthesis falls back to silent per-cue WAV chunks that still exercise SRT-timeline merging. `DUB_TTS_CHUNK_BATCH_SIZE` controls how many cues are synthesized in parallel per batch.

`target_language` is taken from the job record (`Job.target_language`) instead of environment configuration.

## Provider integration

Dub provider API calls, polling, downloads, batching, voice configuration, and mock silent chunk generation live in `app.providers.dub_provider` instead of the video processing worker.
