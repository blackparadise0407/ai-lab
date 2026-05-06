const DEFAULT_API_BASE_URL = 'http://localhost:8000';

export const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? DEFAULT_API_BASE_URL;

export type JobStatus =
  | 'created'
  | 'uploaded'
  | 'processing'
  | 'waiting_provider'
  | 'finalizing'
  | 'completed'
  | 'failed'
  | 'canceled';

export interface Job {
  id: number;
  external_job_id: string;
  source_language: string;
  target_language: string;
  status: JobStatus;
  current_step?: string | null;
  progress_percent: number;
  created_at: string;
  updated_at: string;
}

export interface Artifact {
  id: number;
  job_id: number;
  artifact_type: string;
  storage_url: string;
  content_type?: string | null;
  created_at: string;
}

export interface ProviderRequest {
  id: number;
  job_id: number;
  provider_name: string;
  provider_request_id: string;
  status: string;
  callback_received: boolean;
  retry_count: number;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

export async function createJob(sourceLanguage: string, targetLanguage: string) {
  const response = await fetch(`${apiBaseUrl}/v1/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_language: sourceLanguage, target_language: targetLanguage }),
  });

  return parseJsonResponse<Job>(response);
}

export async function uploadSourceVideo(jobId: number, file: File) {
  const body = new FormData();
  body.append('file', file);

  const response = await fetch(`${apiBaseUrl}/v1/jobs/${jobId}/video`, {
    method: 'POST',
    body,
  });

  return parseJsonResponse<Job>(response);
}

export async function getJob(jobId: number) {
  const response = await fetch(`${apiBaseUrl}/v1/jobs/${jobId}`);
  return parseJsonResponse<Job>(response);
}

export async function getArtifacts(jobId: number) {
  const response = await fetch(`${apiBaseUrl}/v1/artifacts/job/${jobId}`);
  return parseJsonResponse<Artifact[]>(response);
}

export async function getProviderRequests(jobId: number) {
  const response = await fetch(`${apiBaseUrl}/v1/provider-requests/job/${jobId}`);
  return parseJsonResponse<ProviderRequest[]>(response);
}

function isExternalArtifactUrl(artifact: Artifact) {
  return /^https?:\/\//i.test(artifact.storage_url);
}

export function getArtifactDownloadUrl(artifact: Artifact) {
  if (isExternalArtifactUrl(artifact)) {
    return artifact.storage_url;
  }

  return `${apiBaseUrl}/v1/artifacts/${artifact.id}/download`;
}

export function getArtifactPreviewUrl(artifact: Artifact) {
  if (isExternalArtifactUrl(artifact)) {
    return artifact.storage_url;
  }

  return `${getArtifactDownloadUrl(artifact)}?disposition=inline`;
}
