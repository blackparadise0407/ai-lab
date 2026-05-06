# AI Lab Dubbing Pipeline

AI Lab Dubbing Pipeline is a job-based platform for turning source videos into dubbed outputs with subtitles.

## What the platform does

1. Ingest source video.
2. Extract source audio.
3. Transcribe with Whisper.
4. Translate subtitles from Chinese (ZH) to Vietnamese (VI).
5. Split the translated SRT into per-subtitle TTS chunks.
6. Generate chunks with the dub provider in bounded parallel batches.
7. Rebuild the dubbed track by placing each chunk on the SRT timeline.
8. Merge/mux dubbed audio with the original video and subtitle tracks.
9. Publish output artifacts.

## Repository structure

- `apps/core`: API backend (job creation, state tracking, callback handling)
- `apps/worker`: asynchronous workers (transcription, translation, synthesis orchestration, muxing)
- `apps/web`: frontend dashboard (upload, monitoring, download)
- `services/media`: FFmpeg and audio/video processing helpers
- `packages/shared/schemas`: shared API and event schemas
- `packages/shared/utils`: shared utility modules
- `infra/docker`: Docker/Compose assets
- `infra/nginx`: reverse-proxy configuration
- `infra/terraform`: infrastructure as code
- `scripts`: local/devops helper scripts
- `docs`: architecture, API contracts, and runbooks

## Workflow status model

Recommended parent job statuses:

- `created`
- `uploaded`
- `processing`
- `waiting_provider`
- `finalizing`
- `completed`
- `failed`
- `canceled`

## Next documentation milestones

- Add `docs/API_CONTRACT.md` for REST endpoints and callback schemas.
- Add `docs/RUNBOOK.md` for retry/recovery and operational guidance.
- Add `docs/LOCAL_DEV.md` for setup and local execution.
