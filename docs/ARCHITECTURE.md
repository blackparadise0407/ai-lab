# Architecture (Draft)

## 1) System overview

This system processes long-running media jobs asynchronously. A user submits a video, and workers perform transcription, translation, TTS generation, and final muxing. The platform tracks status and returns artifacts (dubbed video, subtitle files, and optional audio-only outputs).

## 2) High-level components

### `apps/core` (API service)

Responsibilities:
- Provide REST endpoints for job lifecycle (`create`, `start`, `status`, `cancel`).
- Accept upload metadata or source URL references.
- Validate request payloads and state transitions.
- Receive provider callbacks (e.g., TTS completion).
- Persist and expose job progress/artifacts.

### `apps/worker` (async processing)

Responsibilities:
- Execute pipeline steps outside request/response cycle.
- Invoke Whisper transcription and subtitle generation.
- Run translation and chunked TTS orchestration logic.
- Delegate TTS provider requests to provider-client adapters and handle retry/backoff orchestration.
- Perform final media assembly and publish outputs.

### `apps/web` (React dashboard)

Responsibilities:
- Provide a client-rendered React/Vite dashboard; no SSR or Next.js runtime is required.
- Create jobs and upload source videos through the Core API.
- Load existing jobs by numeric ID and poll active jobs every five seconds.
- Display per-job status/progress, current pipeline step, provider requests, and generated artifacts.
- Surface request errors from the Core API so operators can retry manually.

### `services/media`

Responsibilities:
- FFmpeg wrappers for audio extraction and muxing.
- Duration checks, padding/trim, and normalization helpers.
- Media validation utilities (codec, sample rate, corruption checks).

### `packages/shared/schemas`

Responsibilities:
- Shared request/response models.
- Event payload contracts for webhook/callback processing.
- Status enums and validation schemas.

### `packages/shared/utils`

Responsibilities:
- Shared formatting/time conversion utilities.
- Common idempotency, retry, and logging helpers.

## 3) Processing pipeline

1. **Ingest**: register job and store source asset.
2. **Extract audio**: convert to Whisper-friendly format (e.g., mono/16k).
3. **Transcribe**: produce timestamped source segments.
4. **Translate**: convert ZH text to VI text.
5. **Chunk TTS input**: split translated subtitles into one synthesis request per SRT cue.
6. **Synthesize speech**: send cues to the provider in bounded parallel batches and capture returned audio chunks.
7. **Rebuild dubbed audio**: place each returned chunk at its SRT start timestamp and mix the chunks into one dubbed track.
8. **Finalize media**: merge dubbed audio + subtitles into final video.
9. **Publish artifacts**: expose signed URLs and mark job complete.

## 4) Data and state

Minimum persistent entities:
- `jobs`: top-level lifecycle, progress, current step, error object.
- `artifacts`: source + generated file locations.
- `provider_requests`: external request IDs, callback status, retry counters.

State progression (happy path):
`created -> uploaded -> processing -> waiting_provider -> finalizing -> completed`

Terminal states:
- `failed`
- `canceled`

## 5) Operations and reliability

- Retry transient provider failures with capped exponential backoff.
- Enforce idempotent callback handling to tolerate duplicate events.
- Add timeout watchdogs for long-running provider jobs.
- Store step-level logs for audit and debugging.

## 6) Directory summary

- `apps/core`: API entrypoint, provider clients, and orchestration control plane.
- `apps/worker`: asynchronous compute plane.
- `apps/web`: client-rendered React/Vite user-facing dashboard.
- `services/media`: media toolchain abstraction.
- `packages/shared/*`: cross-service contracts/utilities.
- `infra/*`: deployment/runtime configuration.
- `scripts`: developer and operations utilities.

## 7) Frontend dashboard runtime

The dashboard is a static React app built with Vite. In local development it runs on `http://localhost:5173` and calls the Core API at `http://localhost:8000` unless `VITE_API_BASE_URL` is provided. The Core API enables CORS for the local Vite origins so browser-based job creation, video upload, polling, artifact inspection, and provider-request inspection work without a reverse proxy.
