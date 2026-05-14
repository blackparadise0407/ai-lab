import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Loader2, RefreshCw, Send } from "lucide-react";

import { useErrorToast } from "../../hooks/useErrorToast";
import type { JobEventPayload } from "../../interfaces/job";
import { getErrorMessage } from "../../lib/format";
import { cn } from "../../lib/utils";
import {
  cancelJob,
  getArtifacts,
  getJob,
  getProviderRequests,
  retryJob,
} from "../../services/api";
import { subscribeToJobEvents } from "../../services/jobEvents";
import { Confirm } from "../common/Confirm";
import { EmptyState } from "../common/EmptyState";
import { PageHeader } from "../common/PageHeader";
import { Button, buttonVariants } from "../ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../ui/card";
import {
  ArtifactRow,
  cancelableStatuses,
  DataPanel,
  JobStatusCard,
  ProviderRequestRow,
  StatusBadge,
} from "./job-detail-ui";

function parseJobId(jobIdParam: string | undefined) {
  if (!jobIdParam) return null;

  const parsedJobId = Number(jobIdParam);
  return Number.isInteger(parsedJobId) && parsedJobId > 0 ? parsedJobId : null;
}

export default function JobDetailPage() {
  const { jobId: jobIdParam } = useParams();
  const jobId = parseJobId(jobIdParam);
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);
  const [socketStatus, setSocketStatus] = useState<
    "idle" | "connected" | "disconnected" | "error"
  >("idle");

  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId!),
    enabled: jobId !== null,
  });

  const artifactsQuery = useQuery({
    queryKey: ["artifacts", jobId],
    queryFn: () => getArtifacts(jobId!),
    enabled: jobId !== null,
  });

  const providerRequestsQuery = useQuery({
    queryKey: ["provider-requests", jobId],
    queryFn: () => getProviderRequests(jobId!),
    enabled: jobId !== null,
  });

  useEffect(() => {
    if (jobId === null) {
      setSocketStatus("idle");
      return undefined;
    }

    return subscribeToJobEvents(jobId, {
      onOpen: () => setSocketStatus("connected"),
      onError: () => setSocketStatus("error"),
      onClose: () => setSocketStatus("disconnected"),
      onMessage: (payload: JobEventPayload) => {
        if (payload.job) {
          queryClient.setQueryData(["job", jobId], payload.job);
        }
        if (payload.artifacts) {
          queryClient.setQueryData(["artifacts", jobId], payload.artifacts);
        }
        if (payload.provider_requests) {
          queryClient.setQueryData(
            ["provider-requests", jobId],
            payload.provider_requests,
          );
        }
      },
    });
  }, [jobId, queryClient]);

  const retryJobMutation = useMutation({
    mutationFn: (targetJobId: number) => retryJob(targetJobId),
    onSuccess: async (retriedJob) => {
      setActionError(null);
      queryClient.setQueryData(["job", retriedJob.id], retriedJob);
      await refreshJob(retriedJob.id);
    },
    onError: (error) => {
      setActionError(getErrorMessage(error, "Unable to retry this job."));
    },
  });

  const cancelJobMutation = useMutation({
    mutationFn: (targetJobId: number) => cancelJob(targetJobId),
    onSuccess: async (canceledJob) => {
      setActionError(null);
      queryClient.setQueryData(["job", canceledJob.id], canceledJob);
      await refreshJob(canceledJob.id);
    },
    onError: (error) => {
      setActionError(getErrorMessage(error, "Unable to cancel this job."));
    },
  });

  const job = jobQuery.data ?? null;
  const artifacts = artifactsQuery.data ?? [];
  const providerRequests = providerRequestsQuery.data ?? [];
  const isRefreshing =
    jobQuery.isFetching ||
    artifactsQuery.isFetching ||
    providerRequestsQuery.isFetching;
  const isLoading =
    jobQuery.isLoading || artifactsQuery.isLoading || providerRequestsQuery.isLoading;
  const queryError = jobQuery.error ?? artifactsQuery.error ?? providerRequestsQuery.error;
  const error =
    actionError ??
    (queryError ? getErrorMessage(queryError, "Unable to load job details.") : null);

  useErrorToast(error, "Job detail error");

  async function refreshJob(targetJobId = jobId) {
    if (!targetJobId) return;

    setActionError(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["job", targetJobId] }),
      queryClient.invalidateQueries({ queryKey: ["artifacts", targetJobId] }),
      queryClient.invalidateQueries({
        queryKey: ["provider-requests", targetJobId],
      }),
    ]);
  }

  function handleRetryJob() {
    if (!job || job.status !== "failed") return;
    retryJobMutation.mutate(job.id);
  }

  function handleCancelJob() {
    if (!job || !cancelableStatuses.has(job.status)) return;
    cancelJobMutation.mutate(job.id);
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 lg:px-8">
      <PageHeader
        eyebrow="Job inspection"
        title={job ? `Job #${job.id}` : "Job details"}
        description="Inspect pipeline status, generated artifacts, provider callbacks, and operational controls for one dubbing job."
      />

      <Card className="mt-8 mb-6 bg-card/90 shadow-xl shadow-slate-900/5">
        <CardHeader>
          <div>
            <CardDescription className="font-black uppercase tracking-[0.18em] text-primary">
              Controls
            </CardDescription>
            <CardTitle className="mt-2 text-2xl">
              {job ? job.external_job_id : jobId ? `Job ID ${jobId}` : "Invalid job"}
            </CardTitle>
            <p className="mt-2 text-sm text-muted-foreground">
              Websocket {socketStatus}
            </p>
          </div>
          <CardAction>{job && <StatusBadge status={job.status} />}</CardAction>
        </CardHeader>
        <CardContent>
          {jobId === null ? (
            <EmptyState>Enter a numeric job ID in the URL to inspect a job.</EmptyState>
          ) : isLoading ? (
            <EmptyState>
              <span className="inline-flex items-center gap-2">
                <Loader2 className="size-4 animate-spin" /> Loading job details…
              </span>
            </EmptyState>
          ) : error && !job ? (
            <EmptyState>{error}</EmptyState>
          ) : (
            <div className="flex flex-wrap gap-3">
              <Button
                variant="secondary"
                type="button"
                onClick={() => refreshJob()}
                disabled={isRefreshing}
              >
                <RefreshCw className={cn(isRefreshing && "animate-spin")} />
                Refresh
              </Button>
              {job?.status === "failed" && (
                <Button
                  variant="secondary"
                  type="button"
                  onClick={handleRetryJob}
                  disabled={retryJobMutation.isPending}
                >
                  <RefreshCw
                    className={cn(retryJobMutation.isPending && "animate-spin")}
                  />
                  {retryJobMutation.isPending ? "Retrying…" : "Retry"}
                </Button>
              )}
              {job && cancelableStatuses.has(job.status) && (
                <Confirm
                  title="Cancel job?"
                  description="Cancel this job? Partial intermediate artifacts may remain available for retry diagnostics."
                  confirmLabel="Confirm"
                  onConfirm={handleCancelJob}
                >
                  <Button
                    variant="secondary"
                    type="button"
                    disabled={cancelJobMutation.isPending}
                  >
                    {cancelJobMutation.isPending ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <Ban />
                    )}
                    {cancelJobMutation.isPending ? "Canceling…" : "Cancel"}
                  </Button>
                </Confirm>
              )}
              {job?.status === "completed" && (
                <Link
                  className={buttonVariants({ variant: "secondary" })}
                  to={`/publish?jobId=${job.id}`}
                >
                  <Send />
                  Publish
                </Link>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <JobStatusCard job={job} />

      <section className="grid gap-6 lg:grid-cols-2">
        <DataPanel
          title="Artifacts"
          count={artifacts.length}
          emptyLabel="No artifacts yet"
        >
          {artifacts.map((artifact) => (
            <ArtifactRow artifact={artifact} key={artifact.id} />
          ))}
        </DataPanel>

        <DataPanel
          title="Provider requests"
          count={providerRequests.length}
          emptyLabel="No provider requests yet"
        >
          {providerRequests.map((request) => (
            <ProviderRequestRow request={request} key={request.id} />
          ))}
        </DataPanel>
      </section>
    </div>
  );
}
