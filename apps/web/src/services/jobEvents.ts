import type { JobEventPayload } from "../interfaces/job";
import { apiBaseUrl } from "./api";

export type JobEventHandlers = {
  onMessage: (payload: JobEventPayload) => void;
  onOpen?: () => void;
  onError?: () => void;
  onClose?: () => void;
};

function getEventsUrl(pathname: string) {
  const url = new URL(apiBaseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = pathname;
  url.search = "";
  return url.toString();
}

export function getJobEventsUrl(jobId: number) {
  return getEventsUrl(`/v1/jobs/${jobId}/events`);
}

export function getJobsEventsUrl() {
  return getEventsUrl("/v1/jobs/events");
}

function subscribeToWebSocket(url: string, handlers: JobEventHandlers) {
  const socket = new WebSocket(url);

  socket.addEventListener("open", () => handlers.onOpen?.());
  socket.addEventListener("error", () => handlers.onError?.());
  socket.addEventListener("close", () => handlers.onClose?.());
  socket.addEventListener("message", (event) => {
    handlers.onMessage(JSON.parse(event.data) as JobEventPayload);
  });

  return () => socket.close();
}

export function subscribeToJobEvents(
  jobId: number,
  handlers: JobEventHandlers,
) {
  return subscribeToWebSocket(getJobEventsUrl(jobId), handlers);
}

export function subscribeToJobsEvents(handlers: JobEventHandlers) {
  return subscribeToWebSocket(getJobsEventsUrl(), handlers);
}
