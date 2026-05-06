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

# YouTube Data API upload adapter and connector.
# Connector mode stores user-granted access/refresh tokens in SQLite; only app credentials live here.
# If all YouTube OAuth values are omitted, YouTube uploads return mock tracking metadata unless a connector token is selected.
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REDIRECT_URI=http://localhost:8000/v1/connectors/youtube/callback
PUBLIC_API_BASE_URL=http://localhost:8000

# Optional legacy single-account fallback for uploads without connected_account_id.
YOUTUBE_REFRESH_TOKEN=
YOUTUBE_TOKEN_URI=https://oauth2.googleapis.com/token
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

Upload provider publishing uses an adapter interface in `app.providers.upload_provider`. The first supported adapters are `youtube`, `facebook`, and `tiktok`. The YouTube adapter uses the YouTube Data API `videos.insert` flow with OAuth credentials, resumable media uploads, category/tags metadata, valid privacy values (`public`, `private`, `unlisted`), and exponential-backoff retries for retriable upload failures. If no YouTube OAuth credentials are configured, it falls back to mock tracking metadata for local development. Facebook and TikTok still use the generic token-authenticated multipart adapter and return mock metadata when their upload URLs are omitted. Publish a completed job with `POST /v1/jobs/{job_id}/uploads` and a body containing `platform`, optional `connected_account_id`, `title`, optional `description`, and optional `privacy`.

### YouTube connector flow

For multi-account YouTube publishing, configure `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and either `YOUTUBE_REDIRECT_URI` or `PUBLIC_API_BASE_URL`. Add the callback URL to the Google OAuth client, then send the browser to `GET /v1/connectors/youtube/authorize`. Google opens a consent screen for `https://www.googleapis.com/auth/youtube.upload`, then calls `GET /v1/connectors/youtube/callback` with an authorization code. The Core API exchanges that code for tokens and stores a connected account row. The dashboard lists connected accounts from `GET /v1/connectors?platform=youtube` and includes the chosen `connected_account_id` in the publish request.

This connector is intentionally not tied to app authentication yet. Until app auth is added, connected accounts are shared by this Core API instance, so do not expose these endpoints publicly without adding authentication and token encryption.
