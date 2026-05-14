import type {
  Artifact,
  ConnectedAccount,
  DubVoiceListResponse,
  Job,
  JobListResponse,
  ProviderRequest,
  PublishUploadRequest,
  PublishUploadResponse,
  VideoCollection,
  VideoCollectionCreateRequest,
  VideoCollectionDetail,
  VideoCollectionListResponse,
  VideoSegment,
  WhisperModelName,
} from '../interfaces/job';

const DEFAULT_API_BASE_URL = 'http://localhost:8000';

export const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? DEFAULT_API_BASE_URL;

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const message = await getResponseErrorMessage(response);
    throw new Error(message || `${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

async function getResponseErrorMessage(response: Response) {
  const rawMessage = await response.text();
  if (!rawMessage) return '';

  try {
    const parsed = JSON.parse(rawMessage) as { detail?: unknown };
    if (typeof parsed.detail === 'string') {
      return parsed.detail;
    }
    if (Array.isArray(parsed.detail)) {
      return parsed.detail.map((item) => JSON.stringify(item)).join('; ');
    }
  } catch {
    return rawMessage;
  }

  return rawMessage;
}

export async function createJob(
  sourceLanguage: string,
  targetLanguage: string,
  modelName: WhisperModelName = 'medium',
  voiceId?: string | null,
  outputVideoSpeed = 1,
  originalAudioVolume = 0.15,
  translationContext?: string | null,
) {
  const response = await fetch(`${apiBaseUrl}/v1/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_language: sourceLanguage,
      target_language: targetLanguage,
      model_name: modelName,
      translation_context: translationContext || null,
      voice_id: voiceId || null,
      output_video_speed: outputVideoSpeed,
      original_audio_volume: originalAudioVolume,
    }),
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

export async function deleteJob(jobId: number) {
  const response = await fetch(`${apiBaseUrl}/v1/jobs/${jobId}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    const message = await getResponseErrorMessage(response);
    throw new Error(message || `${response.status} ${response.statusText}`);
  }
}

export async function retryJob(jobId: number) {
  const response = await fetch(`${apiBaseUrl}/v1/jobs/${jobId}/retry`, {
    method: 'POST',
  });
  return parseJsonResponse<Job>(response);
}

export async function cancelJob(jobId: number) {
  const response = await fetch(`${apiBaseUrl}/v1/jobs/${jobId}/cancel`, {
    method: 'POST',
  });
  return parseJsonResponse<Job>(response);
}

export async function getJobs(
  filters: {
    status?: Job['status'];
    sourceLanguage?: string;
    targetLanguage?: string;
    currentStep?: string;
    limit?: number;
    offset?: number;
  } = {},
) {
  const searchParams = new URLSearchParams();
  if (filters.status) {
    searchParams.set('status', filters.status);
  }
  if (filters.sourceLanguage) {
    searchParams.set('source_language', filters.sourceLanguage);
  }
  if (filters.targetLanguage) {
    searchParams.set('target_language', filters.targetLanguage);
  }
  if (filters.currentStep) {
    searchParams.set('current_step', filters.currentStep);
  }
  if (filters.limit !== undefined) {
    searchParams.set('limit', String(filters.limit));
  }
  if (filters.offset !== undefined) {
    searchParams.set('offset', String(filters.offset));
  }

  const query = searchParams.toString();
  const response = await fetch(`${apiBaseUrl}/v1/jobs${query ? `?${query}` : ''}`);
  return parseJsonResponse<JobListResponse>(response);
}

export async function getDubProviderVoices(refresh = false, languageCode = 'vi-VN') {
  const searchParams = new URLSearchParams({ language_code: languageCode });
  if (refresh) {
    searchParams.set('refresh', 'true');
  }

  const response = await fetch(`${apiBaseUrl}/v1/dub-provider/voices?${searchParams}`);
  return parseJsonResponse<DubVoiceListResponse>(response);
}

export async function getVideoCollections(
  filters: { status?: VideoCollection['status']; limit?: number; offset?: number } = {},
) {
  const searchParams = new URLSearchParams();
  if (filters.status) {
    searchParams.set('status', filters.status);
  }
  if (filters.limit !== undefined) {
    searchParams.set('limit', String(filters.limit));
  }
  if (filters.offset !== undefined) {
    searchParams.set('offset', String(filters.offset));
  }

  const query = searchParams.toString();
  const response = await fetch(`${apiBaseUrl}/v1/video-collections${query ? `?${query}` : ''}`);
  return parseJsonResponse<VideoCollectionListResponse>(response);
}

export async function getVideoCollection(collectionId: number) {
  const response = await fetch(`${apiBaseUrl}/v1/video-collections/${collectionId}`);
  return parseJsonResponse<VideoCollectionDetail>(response);
}

export async function deleteVideoCollection(collectionId: number) {
  const response = await fetch(`${apiBaseUrl}/v1/video-collections/${collectionId}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    const message = await getResponseErrorMessage(response);
    throw new Error(message || `${response.status} ${response.statusText}`);
  }
}

export async function getVideoCollectionSegments(collectionId: number) {
  const response = await fetch(`${apiBaseUrl}/v1/video-collections/${collectionId}/segments`);
  return parseJsonResponse<VideoSegment[]>(response);
}

export async function createVideoCollection(payload: VideoCollectionCreateRequest) {
  const response = await fetch(`${apiBaseUrl}/v1/video-collections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  return parseJsonResponse<VideoCollection>(response);
}

export async function uploadVideoCollectionSource(collectionId: number, file: File) {
  const body = new FormData();
  body.append('file', file);

  const response = await fetch(`${apiBaseUrl}/v1/video-collections/${collectionId}/video`, {
    method: 'POST',
    body,
  });

  return parseJsonResponse<VideoCollectionDetail>(response);
}

export async function getArtifacts(jobId: number) {
  const response = await fetch(`${apiBaseUrl}/v1/artifacts/job/${jobId}`);
  return parseJsonResponse<Artifact[]>(response);
}

export async function getProviderRequests(jobId: number) {
  const response = await fetch(`${apiBaseUrl}/v1/provider-requests/job/${jobId}`);
  return parseJsonResponse<ProviderRequest[]>(response);
}

export async function getConnectedAccounts(platform?: string) {
  const searchParams = platform ? `?platform=${encodeURIComponent(platform)}` : '';
  const response = await fetch(`${apiBaseUrl}/v1/connectors${searchParams}`);
  return parseJsonResponse<ConnectedAccount[]>(response);
}

export function getYouTubeAuthorizeUrl() {
  const redirectAfter = `${window.location.origin}${window.location.pathname}${window.location.search}`;
  return `${apiBaseUrl}/v1/connectors/youtube/authorize?redirect_after=${encodeURIComponent(redirectAfter)}`;
}

export async function deleteConnectedAccount(connectedAccountId: number) {
  const response = await fetch(`${apiBaseUrl}/v1/connectors/${connectedAccountId}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    const message = await getResponseErrorMessage(response);
    throw new Error(message || `${response.status} ${response.statusText}`);
  }
}

export async function publishJobUpload(jobId: number, payload: PublishUploadRequest) {
  const response = await fetch(`${apiBaseUrl}/v1/jobs/${jobId}/uploads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  return parseJsonResponse<PublishUploadResponse>(response);
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

  return `${apiBaseUrl}/v1/artifacts/${artifact.id}/preview`;
}
