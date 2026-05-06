import React, { FormEvent, useEffect, useMemo, useState } from 'react';
import ReactDOM from 'react-dom/client';
import {
  Artifact,
  Job,
  ProviderRequest,
  apiBaseUrl,
  createJob,
  getArtifacts,
  getJob,
  getProviderRequests,
  uploadSourceVideo,
} from './api';
import './styles.css';

const statusLabels: Record<Job['status'], string> = {
  created: 'Created',
  uploaded: 'Uploaded',
  processing: 'Processing',
  waiting_provider: 'Waiting provider',
  finalizing: 'Finalizing',
  completed: 'Completed',
  failed: 'Failed',
  canceled: 'Canceled',
};

const statusOrder: Job['status'][] = [
  'created',
  'uploaded',
  'processing',
  'waiting_provider',
  'finalizing',
  'completed',
];

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function App() {
  const [sourceLanguage, setSourceLanguage] = useState('zh');
  const [targetLanguage, setTargetLanguage] = useState('vi');
  const [file, setFile] = useState<File | null>(null);
  const [jobIdInput, setJobIdInput] = useState('');
  const [job, setJob] = useState<Job | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [providerRequests, setProviderRequests] = useState<ProviderRequest[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeStepIndex = useMemo(() => {
    if (!job) return -1;
    return statusOrder.indexOf(job.status);
  }, [job]);

  async function refreshDashboard(jobId = job?.id) {
    if (!jobId) return;

    setIsLoading(true);
    setError(null);
    try {
      const [jobResponse, artifactResponse, providerResponse] = await Promise.all([
        getJob(jobId),
        getArtifacts(jobId),
        getProviderRequests(jobId),
      ]);
      setJob(jobResponse);
      setArtifacts(artifactResponse);
      setProviderRequests(providerResponse);
      setJobIdInput(String(jobResponse.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to refresh the dashboard.');
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCreateAndUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError('Choose a source video before creating a job.');
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      const created = await createJob(sourceLanguage, targetLanguage);
      const uploaded = await uploadSourceVideo(created.id, file);
      setJob(uploaded);
      setJobIdInput(String(uploaded.id));
      await refreshDashboard(uploaded.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to create and upload the job.');
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleLoadExisting(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsedId = Number(jobIdInput);
    if (!Number.isInteger(parsedId) || parsedId <= 0) {
      setError('Enter a valid numeric job ID.');
      return;
    }

    await refreshDashboard(parsedId);
  }

  useEffect(() => {
    if (!job || ['completed', 'failed', 'canceled'].includes(job.status)) return;

    const intervalId = window.setInterval(() => {
      refreshDashboard(job.id);
    }, 5000);

    return () => window.clearInterval(intervalId);
  }, [job?.id, job?.status]);

  return (
    <main className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">AI Lab Dubbing Pipeline</p>
          <h1>React dashboard for creating, tracking, and reviewing dubbing jobs.</h1>
          <p className="hero-copy">
            Create a pipeline job, upload source video, watch status updates, and inspect the
            generated artifacts and provider requests from one lightweight client-side app.
          </p>
        </div>
        <div className="api-card">
          <span>Connected API</span>
          <strong>{apiBaseUrl}</strong>
        </div>
      </section>

      {error && <div className="alert">{error}</div>}

      <section className="grid two-column">
        <form className="panel" onSubmit={handleCreateAndUpload}>
          <div className="panel-header">
            <span className="step-number">1</span>
            <div>
              <h2>Create pipeline job</h2>
              <p>Defaults match the current ZH → VI dubbing workflow.</p>
            </div>
          </div>
          <label>
            Source language
            <input value={sourceLanguage} onChange={(event) => setSourceLanguage(event.target.value)} />
          </label>
          <label>
            Target language
            <input value={targetLanguage} onChange={(event) => setTargetLanguage(event.target.value)} />
          </label>
          <label>
            Source video
            <input
              type="file"
              accept="video/*"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Creating and uploading…' : 'Create job and upload video'}
          </button>
        </form>

        <form className="panel" onSubmit={handleLoadExisting}>
          <div className="panel-header">
            <span className="step-number">2</span>
            <div>
              <h2>Open existing job</h2>
              <p>Use a job ID from Swagger, logs, or a previous dashboard session.</p>
            </div>
          </div>
          <label>
            Job ID
            <input
              inputMode="numeric"
              placeholder="Example: 1"
              value={jobIdInput}
              onChange={(event) => setJobIdInput(event.target.value)}
            />
          </label>
          <button type="submit" disabled={isLoading}>
            {isLoading ? 'Loading…' : 'Load job'}
          </button>
          {job && (
            <button className="secondary" type="button" onClick={() => refreshDashboard(job.id)}>
              Refresh now
            </button>
          )}
        </form>
      </section>

      <section className="panel dashboard-panel">
        <div className="panel-header split">
          <div>
            <p className="eyebrow">Pipeline status</p>
            <h2>{job ? `Job #${job.id} · ${job.external_job_id}` : 'No job loaded'}</h2>
          </div>
          {job && <span className={`status-pill status-${job.status}`}>{statusLabels[job.status]}</span>}
        </div>

        {job ? (
          <>
            <div className="progress-track" aria-label={`Progress ${job.progress_percent}%`}>
              <span style={{ width: `${job.progress_percent}%` }} />
            </div>
            <div className="job-meta">
              <span>{job.source_language.toUpperCase()} → {job.target_language.toUpperCase()}</span>
              <span>{job.progress_percent}% complete</span>
              <span>Updated {formatDate(job.updated_at)}</span>
              <span>{job.current_step ?? 'Waiting for next step'}</span>
            </div>
            <ol className="timeline">
              {statusOrder.map((status, index) => (
                <li key={status} className={index <= activeStepIndex ? 'active' : ''}>
                  <span>{index + 1}</span>
                  {statusLabels[status]}
                </li>
              ))}
            </ol>
          </>
        ) : (
          <p className="empty-state">Create a job or load an existing one to see pipeline telemetry.</p>
        )}
      </section>

      <section className="grid two-column">
        <DataPanel title="Artifacts" emptyLabel="No artifacts yet">
          {artifacts.map((artifact) => (
            <article className="data-row" key={artifact.id}>
              <div>
                <strong>{artifact.artifact_type}</strong>
                <p>{artifact.content_type ?? 'Unknown content type'}</p>
              </div>
              {artifact.storage_url.startsWith('http') ? (
                <a href={artifact.storage_url} target="_blank" rel="noreferrer">
                  Open
                </a>
              ) : (
                <code>{artifact.storage_url}</code>
              )}
            </article>
          ))}
        </DataPanel>

        <DataPanel title="Provider requests" emptyLabel="No provider requests yet">
          {providerRequests.map((request) => (
            <article className="data-row" key={request.id}>
              <div>
                <strong>{request.provider_name}</strong>
                <p>{request.provider_request_id}</p>
                {request.last_error && <p className="row-error">{request.last_error}</p>}
              </div>
              <span>{request.status}</span>
            </article>
          ))}
        </DataPanel>
      </section>
    </main>
  );
}

function DataPanel({
  title,
  emptyLabel,
  children,
}: {
  title: string;
  emptyLabel: string;
  children: React.ReactNode[] | React.ReactNode;
}) {
  const childCount = React.Children.count(children);

  return (
    <section className="panel list-panel">
      <div className="panel-header split">
        <h2>{title}</h2>
        <span>{childCount}</span>
      </div>
      {childCount > 0 ? <div className="data-list">{children}</div> : <p className="empty-state">{emptyLabel}</p>}
    </section>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
