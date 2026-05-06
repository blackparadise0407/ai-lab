import type { JobEventPayload } from '../interfaces/job';
import { apiBaseUrl } from './api';

export type JobEventHandlers = {
  onMessage: (payload: JobEventPayload) => void;
  onOpen?: () => void;
  onError?: () => void;
  onClose?: () => void;
};

export function getJobEventsUrl(jobId: number) {
  const url = new URL(apiBaseUrl);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = `/v1/jobs/${jobId}/events`;
  url.search = '';
  return url.toString();
}

export function subscribeToJobEvents(jobId: number, handlers: JobEventHandlers) {
  const socket = new WebSocket(getJobEventsUrl(jobId));

  socket.addEventListener('open', () => handlers.onOpen?.());
  socket.addEventListener('error', () => handlers.onError?.());
  socket.addEventListener('close', () => handlers.onClose?.());
  socket.addEventListener('message', (event) => {
    handlers.onMessage(JSON.parse(event.data) as JobEventPayload);
  });

  return () => socket.close();
}
