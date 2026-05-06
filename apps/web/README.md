# Web Dashboard

React + Vite dashboard for the AI Lab dubbing pipeline. The app is fully client-side; it does not use Next.js or server-side rendering.

## Capabilities

- Create a dubbing job with source and target language codes.
- Upload a source video to start the pipeline.
- Load an existing job by numeric ID.
- Poll active jobs every five seconds until they reach a terminal state.
- Inspect job progress, current step, generated artifacts, and provider requests.

## Run locally

Start the Core API first from `apps/core`:

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Then start the dashboard from `apps/web`:

```bash
npm install
npm run dev
```

Open <http://localhost:5173>. The dashboard points to `http://localhost:8000` by default.

## Configuration

Set `VITE_API_BASE_URL` if the Core API is not running on port `8000`:

```bash
VITE_API_BASE_URL=http://localhost:9000 npm run dev
```

The Core API allows browser requests from `http://localhost:5173` and `http://127.0.0.1:5173` for local development.
