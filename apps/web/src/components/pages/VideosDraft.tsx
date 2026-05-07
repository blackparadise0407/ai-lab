import { AlertCircle, Loader2 } from "lucide-react";

import { uploadPlatformOptions } from "../../constants/uploadPlatforms";
import type {
  ProviderRequest,
  UploadPlatform,
  VideoCollection,
  VideoSegment,
} from "../../interfaces/job";
import { formatDate, getErrorMessage } from "../../lib/format";
import { EmptyState } from "../common/EmptyState";
import { PageHeader } from "../common/PageHeader";
import { Alert, AlertDescription, AlertTitle } from "../ui/alert";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../ui/card";
import { Progress } from "../ui/progress";

export function VideosDraft({
  collections,
  error,
  isLoading,
  onPageChange,
  onPublish,
  onPublishAll,
  page,
  pageSize,
  pendingPublish,
  providerRequestsByJobId,
  publishError,
  segmentsByCollectionId,
  total,
  totalPages,
}: {
  collections: VideoCollection[];
  error: unknown;
  isLoading: boolean;
  onPageChange: (page: number) => void;
  onPublish: (jobId: number, platform: UploadPlatform) => void;
  onPublishAll: (jobIds: number[], platform: UploadPlatform) => void;
  page: number;
  pageSize: number;
  pendingPublish: { jobIds: number[]; platform: UploadPlatform } | null;
  providerRequestsByJobId: Map<number, ProviderRequest[]>;
  publishError: unknown;
  segmentsByCollectionId: Map<number, VideoSegment[]>;
  total: number;
  totalPages: number;
}) {
  return (
    <section className="grid gap-6">
      <PageHeader
        eyebrow="Videos"
        title="Video collections"
        description="Manage each uploaded source video as a collection. Videos over 60 seconds are displayed as ordered chunks so each segment can be processed and published without losing the original grouping."
      />

      {Boolean(error) && (
        <Alert variant="destructive" className="bg-red-50">
          <AlertCircle />
          <AlertTitle>Videos error</AlertTitle>
          <AlertDescription>
            {getErrorMessage(error, "Unable to load video collections.")}
          </AlertDescription>
        </Alert>
      )}

      {Boolean(publishError) && (
        <Alert variant="destructive" className="bg-red-50">
          <AlertCircle />
          <AlertTitle>Publish error</AlertTitle>
          <AlertDescription>
            {getErrorMessage(publishError, "Unable to publish this video.")}
          </AlertDescription>
        </Alert>
      )}

      <Card className="bg-white/90 shadow-xl shadow-slate-900/5">
        <CardHeader>
          <div>
            <CardDescription className="font-black uppercase tracking-[0.18em] text-primary">
              Video library
            </CardDescription>
            <CardTitle className="mt-2 text-2xl">Source video collections</CardTitle>
            <CardDescription>
              One collection represents the original upload. Its chunks remain individually publishable jobs.
            </CardDescription>
          </div>
          <CardAction>
            <Badge variant="secondary">{total} total</Badge>
          </CardAction>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <EmptyState>Loading video collections…</EmptyState>
          ) : collections.length > 0 ? (
            <div className="grid gap-4">
              {collections.map((collection) => {
                const segments = segmentsByCollectionId.get(collection.id) ?? [];
                const completedJobIds = segments
                  .filter((segment) => segment.job?.status === "completed")
                  .map((segment) => segment.job_id);

                return (
                  <article key={collection.id} className="rounded-2xl border bg-white p-4">
                    <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr_auto] lg:items-start">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-lg font-black">
                            {collection.title || collection.original_filename || `Collection #${collection.id}`}
                          </h3>
                          <StatusBadge status={collection.status} />
                        </div>
                        <div className="mt-1 break-all text-sm text-muted-foreground">
                          {collection.external_collection_id}
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2 text-sm">
                          <Badge variant="secondary">
                            {collection.source_language.toUpperCase()} → {collection.target_language.toUpperCase()}
                          </Badge>
                          <Badge variant="secondary">
                            {collection.completed_segment_count}/{collection.segment_count} chunks complete
                          </Badge>
                          {collection.total_duration_seconds !== null && collection.total_duration_seconds !== undefined && (
                            <Badge variant="secondary">
                              {formatDuration(collection.total_duration_seconds)} total
                            </Badge>
                          )}
                        </div>
                      </div>

                      <div className="grid gap-2">
                        <div className="flex items-center justify-between text-sm font-bold">
                          <span>Collection progress</span>
                          <span>{collection.progress_percent}%</span>
                        </div>
                        <Progress value={collection.progress_percent} />
                        <div className="text-sm text-muted-foreground">
                          Updated {formatDate(collection.updated_at)}
                        </div>
                      </div>

                      <div className="flex flex-wrap justify-end gap-2">
                        {uploadPlatformOptions.map((platform) => {
                          const isPending =
                            pendingPublish?.platform === platform.value &&
                            completedJobIds.some((jobId) => pendingPublish.jobIds.includes(jobId));

                          return (
                            <Button
                              key={platform.value}
                              type="button"
                              size="sm"
                              variant="secondary"
                              disabled={pendingPublish !== null || completedJobIds.length === 0}
                              onClick={() => onPublishAll(completedJobIds, platform.value)}
                            >
                              {isPending && <Loader2 className="animate-spin" />}
                              Publish all to {platform.label}
                            </Button>
                          );
                        })}
                      </div>
                    </div>

                    <div className="mt-4 overflow-x-auto rounded-2xl border">
                      <table className="w-full min-w-[64rem] text-left text-sm">
                        <thead className="bg-slate-50 text-xs font-black uppercase tracking-[0.16em] text-muted-foreground">
                          <tr>
                            <th className="px-4 py-3">Chunk</th>
                            <th className="px-4 py-3">Time range</th>
                            <th className="px-4 py-3">Job</th>
                            <th className="px-4 py-3">Status</th>
                            <th className="px-4 py-3">Published platforms</th>
                            <th className="px-4 py-3 text-right">Publish chunk</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y bg-white">
                          {segments.length > 0 ? (
                            segments.map((segment) => {
                              const publishStatuses = getPublishStatuses(
                                providerRequestsByJobId.get(segment.job_id) ?? [],
                              );

                              return (
                                <tr key={segment.id}>
                                  <td className="px-4 py-4 align-top font-black">
                                    Part {segment.sequence_index}
                                  </td>
                                  <td className="px-4 py-4 align-top text-muted-foreground">
                                    {formatDuration(segment.start_seconds)}–{formatDuration(segment.end_seconds)}
                                  </td>
                                  <td className="px-4 py-4 align-top">
                                    <div className="font-black">Job #{segment.job_id}</div>
                                    {segment.job?.external_job_id && (
                                      <div className="mt-1 break-all text-muted-foreground">
                                        {segment.job.external_job_id}
                                      </div>
                                    )}
                                  </td>
                                  <td className="px-4 py-4 align-top">
                                    <StatusBadge status={segment.job?.status ?? "created"} />
                                  </td>
                                  <td className="px-4 py-4 align-top">
                                    <div className="flex flex-wrap gap-2">
                                      {uploadPlatformOptions.map((platform) => (
                                        <PlatformPublishBadge
                                          key={platform.value}
                                          platform={platform.value}
                                          status={publishStatuses.get(platform.value)}
                                        />
                                      ))}
                                    </div>
                                  </td>
                                  <td className="px-4 py-4 align-top">
                                    <div className="flex flex-wrap justify-end gap-2">
                                      {uploadPlatformOptions.map((platform) => {
                                        const isPending =
                                          pendingPublish?.platform === platform.value &&
                                          pendingPublish.jobIds.includes(segment.job_id);

                                        return (
                                          <Button
                                            key={platform.value}
                                            type="button"
                                            size="sm"
                                            variant="secondary"
                                            disabled={
                                              pendingPublish !== null ||
                                              segment.job?.status !== "completed"
                                            }
                                            onClick={() => onPublish(segment.job_id, platform.value)}
                                          >
                                            {isPending && <Loader2 className="animate-spin" />}
                                            {platform.label}
                                          </Button>
                                        );
                                      })}
                                    </div>
                                  </td>
                                </tr>
                              );
                            })
                          ) : (
                            <tr>
                              <td className="px-4 py-6 text-center text-muted-foreground" colSpan={6}>
                                No chunks have been created for this collection yet.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <EmptyState>
              No video collections yet. Upload a source video to create a collection and split long videos into manageable chunks.
            </EmptyState>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3 rounded-2xl border bg-white/80 p-4 text-sm text-muted-foreground shadow-xl shadow-slate-900/5 sm:flex-row sm:items-center sm:justify-between">
        <span>
          Showing {collections.length === 0 ? 0 : page * pageSize + 1}–
          {Math.min((page + 1) * pageSize, total)} of {total} collections
        </span>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={page === 0 || isLoading}
            onClick={() => onPageChange(Math.max(0, page - 1))}
          >
            Previous
          </Button>
          <Badge variant="secondary">
            Page {page + 1} of {totalPages}
          </Badge>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={page + 1 >= totalPages || isLoading}
            onClick={() => onPageChange(Math.min(totalPages - 1, page + 1))}
          >
            Next
          </Button>
        </div>
      </div>
    </section>
  );
}

function getPublishStatuses(providerRequests: ProviderRequest[]) {
  const statuses = new Map<UploadPlatform, ProviderRequest["status"]>();

  providerRequests.forEach((request) => {
    const platform = request.provider_name.replace(
      /^upload_/,
      "",
    ) as UploadPlatform;
    if (uploadPlatformOptions.some((option) => option.value === platform)) {
      statuses.set(platform, request.status);
    }
  });

  return statuses;
}

function PlatformPublishBadge({
  platform,
  status,
}: {
  platform: UploadPlatform;
  status?: ProviderRequest["status"];
}) {
  const label =
    uploadPlatformOptions.find((option) => option.value === platform)?.label ??
    platform;

  if (!status) {
    return <Badge variant="secondary">{label}: not published</Badge>;
  }

  return (
    <Badge className="bg-emerald-100 text-emerald-700">
      {label}: {status}
    </Badge>
  );
}

function StatusBadge({ status }: { status: string }) {
  const isComplete = status === "completed";
  const isFailed = status === "failed";
  const className = isComplete
    ? "bg-emerald-100 text-emerald-700"
    : isFailed
      ? "bg-red-100 text-red-700"
      : undefined;

  return <Badge className={className} variant={className ? undefined : "secondary"}>{status}</Badge>;
}

function formatDuration(totalSeconds: number) {
  const safeSeconds = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(safeSeconds / 60);
  const seconds = safeSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}
