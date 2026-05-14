import type { Job, JobEventPayload, JobListResponse } from "../interfaces/job";

export const runningJobStatuses = new Set<Job["status"]>([
  "created",
  "uploaded",
  "processing",
  "waiting_provider",
  "finalizing",
]);

export function applyJobEventToRunningJobs(
  current: JobListResponse | undefined,
  payload: JobEventPayload,
): JobListResponse | undefined {
  if (payload.items) {
    return {
      items: payload.items.filter((job) => runningJobStatuses.has(job.status)),
      total: payload.total ?? payload.items.length,
      limit: payload.limit ?? payload.items.length,
      offset: payload.offset ?? 0,
    };
  }

  if (!payload.job) {
    return current;
  }

  const fallback: JobListResponse = {
    items: [],
    total: 0,
    limit: 20,
    offset: 0,
  };
  const previous = current ?? fallback;
  const withoutChangedJob = previous.items.filter(
    (job) => job.id !== payload.job!.id,
  );

  if (!runningJobStatuses.has(payload.job.status)) {
    return {
      ...previous,
      items: withoutChangedJob,
      total: Math.max(
        0,
        previous.total -
          (withoutChangedJob.length === previous.items.length ? 0 : 1),
      ),
    };
  }

  return {
    ...previous,
    items: [payload.job, ...withoutChangedJob].sort((left, right) =>
      right.created_at.localeCompare(left.created_at),
    ),
    total:
      withoutChangedJob.length === previous.items.length
        ? previous.total + 1
        : previous.total,
  };
}
