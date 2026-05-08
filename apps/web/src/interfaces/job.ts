export type JobStatus =
  | 'created'
  | 'uploaded'
  | 'processing'
  | 'waiting_provider'
  | 'finalizing'
  | 'completed'
  | 'failed'
  | 'canceled';

export interface JobListResponse {
  items: Job[];
  total: number;
  limit: number;
  offset: number;
}

export interface Job {
  id: number;
  external_job_id: string;
  source_language: string;
  target_language: string;
  voice_id?: string | null;
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

export type UploadPlatform = 'youtube' | 'facebook' | 'tiktok';

export interface ConnectedAccount {
  id: number;
  platform: UploadPlatform;
  provider_account_id: string;
  display_name: string;
  scopes: string;
  expires_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PublishUploadRequest {
  platform: UploadPlatform;
  connected_account_id?: number | null;
  title: string;
  description: string;
  privacy: string;
}

export interface PublishUploadResponse {
  job_id: number;
  platform: UploadPlatform;
  provider_request_id: string;
  remote_url?: string | null;
  status: string;
}

export interface JobEventPayload {
  event: string;
  job?: Job;
  artifacts?: Artifact[];
  provider_requests?: ProviderRequest[];
  job_id?: number;
}

export interface VideoSegmentArtifact {
  id: number;
  job_id: number;
  artifact_type: string;
  storage_url: string;
  content_type?: string | null;
  created_at: string;
}

export interface VideoSegment {
  id: number;
  collection_id: number;
  job_id: number;
  sequence_index: number;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  source_artifact_id?: number | null;
  processed_artifact_id?: number | null;
  created_at: string;
  updated_at: string;
  job?: Job | null;
  source_artifact?: VideoSegmentArtifact | null;
  processed_artifact?: VideoSegmentArtifact | null;
}

export interface VideoCollection {
  id: number;
  external_collection_id: string;
  title?: string | null;
  original_filename?: string | null;
  source_language: string;
  target_language: string;
  voice_id?: string | null;
  source_artifact_id?: number | null;
  total_duration_seconds?: number | null;
  split_threshold_seconds: number;
  status: JobStatus;
  segment_count: number;
  completed_segment_count: number;
  progress_percent: number;
  created_at: string;
  updated_at: string;
}

export interface VideoCollectionDetail extends VideoCollection {
  segments: VideoSegment[];
}

export interface VideoCollectionListResponse {
  items: VideoCollection[];
  total: number;
  limit: number;
  offset: number;
}

export interface VideoCollectionCreateRequest {
  title?: string | null;
  source_language: string;
  target_language: string;
  voice_id?: string | null;
  split_threshold_seconds?: number;
}

export interface DubVoice {
  voice_id: string;
  name: string;
  gender?: string | null;
  language?: string | null;
  accent?: string | null;
  credit_factor?: number | null;
  demo?: string | null;
}

export interface DubVoiceListResponse {
  items: DubVoice[];
  cached: boolean;
  cache_ttl_seconds: number;
}
