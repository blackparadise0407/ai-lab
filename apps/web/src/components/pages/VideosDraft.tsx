import { AlertCircle, Loader2 } from "lucide-react";

import { uploadPlatformOptions } from "../../constants/uploadPlatforms";
import type { Job, ProviderRequest, UploadPlatform } from "../../interfaces/job";
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

export function VideosDraft({
  completedJobs,
  error,
  isLoading,
  onPageChange,
  onPublish,
  page,
  pageSize,
  pendingPublish,
  providerRequestsByJobId,
  publishError,
  total,
  totalPages,
}: {
  completedJobs: Job[];
  error: unknown;
  isLoading: boolean;
  onPageChange: (page: number) => void;
  onPublish: (jobId: number, platform: UploadPlatform) => void;
  page: number;
  pageSize: number;
  pendingPublish: { jobId: number; platform: UploadPlatform } | null;
  providerRequestsByJobId: Map<number, ProviderRequest[]>;
  publishError: unknown;
  total: number;
  totalPages: number;
}) {
  return (
    <section className="grid gap-6">
      <PageHeader
        eyebrow="Videos"
        title="Completed short-video jobs"
        description="Draft list for completed video chunks. Publishing can be run per completed job, and the table tracks which platforms already received each video."
      />

      {Boolean(error) && (
        <Alert variant="destructive" className="bg-red-50">
          <AlertCircle />
          <AlertTitle>Videos error</AlertTitle>
          <AlertDescription>
            {getErrorMessage(error, "Unable to load completed videos.")}
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
            <CardTitle className="mt-2 text-2xl">Completed jobs</CardTitle>
            <CardDescription>
              The future short-video pipeline will split uploads into chunks
              under 60 seconds and create one job per chunk. This draft table is
              ready to show each completed chunk as its own publishable video.
            </CardDescription>
          </div>
          <CardAction>
            <Badge variant="secondary">{total} total</Badge>
          </CardAction>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <EmptyState>Loading completed video jobs…</EmptyState>
          ) : completedJobs.length > 0 ? (
            <div className="overflow-x-auto rounded-2xl border">
              <table className="w-full min-w-[58rem] text-left text-sm">
                <thead className="bg-slate-50 text-xs font-black uppercase tracking-[0.16em] text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Job</th>
                    <th className="px-4 py-3">Languages</th>
                    <th className="px-4 py-3">Completed</th>
                    <th className="px-4 py-3">Published platforms</th>
                    <th className="px-4 py-3 text-right">Publish</th>
                  </tr>
                </thead>
                <tbody className="divide-y bg-white">
                  {completedJobs.map((completedJob) => {
                    const publishStatuses = getPublishStatuses(
                      providerRequestsByJobId.get(completedJob.id) ?? [],
                    );

                    return (
                      <tr key={completedJob.id}>
                        <td className="px-4 py-4 align-top">
                          <div className="font-black">Job #{completedJob.id}</div>
                          <div className="mt-1 break-all text-muted-foreground">
                            {completedJob.external_job_id}
                          </div>
                        </td>
                        <td className="px-4 py-4 align-top">
                          <Badge variant="secondary">
                            {completedJob.source_language.toUpperCase()} →{" "}
                            {completedJob.target_language.toUpperCase()}
                          </Badge>
                        </td>
                        <td className="px-4 py-4 align-top text-muted-foreground">
                          {formatDate(completedJob.updated_at)}
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
                                pendingPublish?.jobId === completedJob.id &&
                                pendingPublish.platform === platform.value;

                              return (
                                <Button
                                  key={platform.value}
                                  type="button"
                                  size="sm"
                                  variant="secondary"
                                  disabled={pendingPublish !== null}
                                  onClick={() =>
                                    onPublish(completedJob.id, platform.value)
                                  }
                                >
                                  {isPending && (
                                    <Loader2 className="animate-spin" />
                                  )}
                                  {platform.label}
                                </Button>
                              );
                            })}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState>
              No completed video jobs yet. Completed chunks will appear here
              after processing finishes.
            </EmptyState>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3 rounded-2xl border bg-white/80 p-4 text-sm text-muted-foreground shadow-xl shadow-slate-900/5 sm:flex-row sm:items-center sm:justify-between">
        <span>
          Showing {completedJobs.length === 0 ? 0 : page * pageSize + 1}–
          {Math.min((page + 1) * pageSize, total)} of {total} completed jobs
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
