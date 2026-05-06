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
DUB_TTS_CHUNK_MAX_ATTEMPTS=3
DUB_TTS_CHUNK_RETRY_DELAY_SECONDS=2
DUB_PROVIDER_VOICE_CODE=hn_female_ngochuyen_full_48k-fhg
DUB_PROVIDER_URL=https://vbee.vn/api/v1/tts
DUB_PROVIDER_APP_ID=
DUB_PROVIDER_TOKEN=

# Optional YouTube Data API upload adapter.
# If all YouTube OAuth values are omitted, YouTube uploads return mock tracking metadata.
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REFRESH_TOKEN=
YOUTUBE_TOKEN_URI=https://oauth2.googleapis.com/token
YOUTUBE_CATEGORY_ID=22
YOUTUBE_TAGS=
YOUTUBE_UPLOAD_CHUNK_SIZE=-1
YOUTUBE_UPLOAD_MAX_RETRIES=10

# Optional generic publishing adapters. If *_UPLOAD_URL is omitted, adapters return mock uploads.
FACEBOOK_UPLOAD_URL=
FACEBOOK_ACCESS_TOKEN=
TIKTOK_UPLOAD_URL=
TIKTOK_ACCESS_TOKEN=
```

If `OPENAI_API_KEY` is not set, subtitle translation falls back to a passthrough mock mode.

If `DUB_PROVIDER_URL` is not set, TTS synthesis falls back to silent per-cue WAV chunks that still exercise SRT-timeline merging. `DUB_TTS_CHUNK_BATCH_SIZE` controls how many cues are synthesized in parallel per batch. Failed chunks are retried without resynthesizing successful chunks in the same batch; configure attempts with `DUB_TTS_CHUNK_MAX_ATTEMPTS` and the initial exponential-backoff delay with `DUB_TTS_CHUNK_RETRY_DELAY_SECONDS`.

`target_language` is taken from the job record (`Job.target_language`) instead of environment configuration.

## Provider integration

Dub provider API calls, polling, downloads, batching, voice configuration, and mock silent chunk generation live in `app.providers.dub_provider` instead of the video processing worker.

Upload provider publishing uses an adapter interface in `app.providers.upload_provider`. The first supported adapters are `youtube`, `facebook`, and `tiktok`. The YouTube adapter uses the YouTube Data API `videos.insert` flow with OAuth refresh-token credentials, resumable media uploads, category/tags metadata, valid privacy values (`public`, `private`, `unlisted`), and exponential-backoff retries for retriable upload failures. If no YouTube OAuth credentials are configured, it falls back to mock tracking metadata for local development. Facebook and TikTok still use the generic token-authenticated multipart adapter and return mock metadata when their upload URLs are omitted. Publish a completed job with `POST /v1/jobs/{job_id}/uploads` and a body containing `platform`, `title`, optional `description`, and optional `privacy`.
