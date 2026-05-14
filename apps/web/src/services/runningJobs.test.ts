import { describe, expect, it } from "vitest";

import type { Job, JobListResponse } from "../interfaces/job";
import { applyJobEventToRunningJobs } from "./runningJobs";

function job(overrides: Partial<Job>): Job {
  return {
    id: 1,
    external_job_id: "job_1",
    source_language: "zh",
    target_language: "vi",
    model_name: "medium",
    translation_context: null,
    voice_id: null,
    output_video_speed: 1,
    original_audio_volume: 0.15,
    status: "created",
    current_step: null,
    progress_percent: 0,
    error_code: null,
    error_message: null,
    created_at: "2026-01-01T12:00:00Z",
    updated_at: "2026-01-01T12:00:00Z",
    ...overrides,
  };
}

describe("applyJobEventToRunningJobs", () => {
  it("upserts streamed jobs that enter a running status", () => {
    const existing = job({ id: 1, external_job_id: "existing" });
    const streamed = job({
      id: 2,
      external_job_id: "streamed",
      status: "processing",
      created_at: "2026-01-01T12:05:00Z",
    });
    const current: JobListResponse = {
      items: [existing],
      total: 1,
      limit: 20,
      offset: 0,
    };

    const result = applyJobEventToRunningJobs(current, {
      event: "job_progress_updated",
      job: streamed,
    });

    expect(result?.items.map((item) => item.external_job_id)).toEqual([
      "streamed",
      "existing",
    ]);
    expect(result?.total).toBe(2);
  });

  it("removes streamed jobs that enter a terminal status", () => {
    const completed = job({
      id: 1,
      external_job_id: "completed",
      status: "completed",
    });
    const current: JobListResponse = {
      items: [job({ id: 1, external_job_id: "completed" })],
      total: 1,
      limit: 20,
      offset: 0,
    };

    const result = applyJobEventToRunningJobs(current, {
      event: "job_completed",
      job: completed,
    });

    expect(result?.items).toEqual([]);
    expect(result?.total).toBe(0);
  });
});
