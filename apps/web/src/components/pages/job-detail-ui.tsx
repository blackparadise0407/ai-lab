import { useMemo, useState, type ReactNode } from "react";
import { Download, ExternalLink, Eye } from "lucide-react";

import type { Artifact, Job, ProviderRequest } from "../../interfaces/job";
import { formatDate } from "../../lib/format";
import { cn } from "../../lib/utils";
import {
  getArtifactDownloadUrl,
  getArtifactPreviewUrl,
} from "../../services/api";
import { EmptyState } from "../common/EmptyState";
import { Badge } from "../ui/badge";
import { Button, buttonVariants } from "../ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../ui/card";
import { Progress } from "../ui/progress";

export const statusLabels: Record<Job["status"], string> = {
  created: "Created",
  uploaded: "Uploaded",
  processing: "Processing",
  waiting_provider: "Waiting provider",
  finalizing: "Finalizing",
  completed: "Completed",
  failed: "Failed",
  canceled: "Canceled",
};

export const statusOrder: Job["status"][] = [
  "created",
  "uploaded",
  "processing",
  "waiting_provider",
  "finalizing",
  "completed",
];

export const cancelableStatuses = new Set<Job["status"]>([
  "created",
  "uploaded",
  "processing",
  "waiting_provider",
  "finalizing",
]);

export function StatusBadge({
  status,
  children = statusLabels[status],
}: {
  status: Job["status"];
  children?: ReactNode;
}) {
  const className = {
    created: "bg-blue-100 text-blue-700",
    uploaded: "bg-blue-100 text-blue-700",
    processing: "bg-amber-100 text-amber-800",
    waiting_provider: "bg-amber-100 text-amber-800",
    finalizing: "bg-amber-100 text-amber-800",
    completed: "bg-emerald-100 text-emerald-700",
    failed: "bg-red-100 text-red-700",
    canceled: "bg-red-100 text-red-700",
  }[status];

  return <Badge className={cn("uppercase", className)}>{children}</Badge>;
}

export function JobStatusCard({ job }: { job: Job | null }) {
  const activeStepIndex = useMemo(() => {
    if (!job) return -1;
    return statusOrder.indexOf(job.status);
  }, [job]);

  return (
    <Card className="mb-6 bg-white/90 shadow-xl shadow-slate-900/5">
      <CardHeader>
        <div>
          <CardDescription className="font-black uppercase tracking-[0.18em] text-primary">
            Pipeline status
          </CardDescription>
          <CardTitle className="mt-2 text-2xl">
            {job ? `Job #${job.id} · ${job.external_job_id}` : "No job loaded"}
          </CardTitle>
        </div>
        <CardAction>{job && <StatusBadge status={job.status} />}</CardAction>
      </CardHeader>

      <CardContent>
        {job ? (
          <div className="grid gap-5">
            <Progress
              value={job.progress_percent}
              aria-label={`Progress ${job.progress_percent}%`}
              className="h-4"
            />
            <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
              <Badge variant="secondary">
                {job.source_language.toUpperCase()} →{" "}
                {job.target_language.toUpperCase()}
              </Badge>
              {job.translation_context && (
                <Badge variant="secondary">Context {job.translation_context}</Badge>
              )}
              <Badge variant="secondary">
                Voice {job.voice_id || "provider default"}
              </Badge>
              <Badge variant="secondary">Speed {job.output_video_speed}x</Badge>
              <Badge variant="secondary">
                Original volume {job.original_audio_volume}
              </Badge>
              <Badge variant="secondary">
                {job.progress_percent}% complete
              </Badge>
              <Badge variant="secondary">Updated {formatDate(job.updated_at)}</Badge>
              <Badge variant="secondary">
                {job.current_step ?? "Waiting for next step"}
              </Badge>
              {job.error_message && (
                <Badge className="bg-red-100 text-red-700">
                  Error {job.error_message}
                </Badge>
              )}
            </div>
            <ol className="grid gap-3 lg:grid-cols-6">
              {statusOrder.map((status, index) => (
                <li
                  key={status}
                  className={cn(
                    "flex items-center gap-3 rounded-xl border bg-slate-50 p-3 text-sm font-bold text-muted-foreground",
                    index <= activeStepIndex &&
                      "border-primary/20 bg-primary/10 text-primary",
                  )}
                >
                  <span className="flex size-7 items-center justify-center rounded-full bg-white text-xs shadow-sm">
                    {index + 1}
                  </span>
                  {statusLabels[status]}
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <EmptyState>
            Create a job or load an existing one to see pipeline telemetry.
          </EmptyState>
        )}
      </CardContent>
    </Card>
  );
}

export function DataPanel({
  title,
  count,
  emptyLabel,
  children,
}: {
  title: string;
  count: number;
  emptyLabel: string;
  children: ReactNode;
}) {
  return (
    <Card className="max-h-[34rem] min-h-72 bg-white/90 shadow-xl shadow-slate-900/5">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardAction>
          <Badge variant="secondary">{count}</Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 overflow-y-auto pr-4">
        {count > 0 ? (
          <div className="grid gap-3">{children}</div>
        ) : (
          <EmptyState>{emptyLabel}</EmptyState>
        )}
      </CardContent>
    </Card>
  );
}

export function ArtifactRow({ artifact }: { artifact: Artifact }) {
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  const previewUrl = getArtifactPreviewUrl(artifact);

  return (
    <article className="flex flex-col gap-4 rounded-2xl border bg-slate-50 p-4">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <strong>{artifact.artifact_type}</strong>
          <p className="mt-1 break-all text-sm text-muted-foreground">
            {artifact.content_type ?? "Unknown content type"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => setIsPreviewOpen((current) => !current)}
            aria-expanded={isPreviewOpen}
          >
            <Eye />
            {isPreviewOpen ? "Hide preview" : "Preview"}
          </Button>
          <a
            className={buttonVariants({ variant: "secondary", size: "sm" })}
            href={previewUrl}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink />
            Open
          </a>
          <a
            className={buttonVariants({ variant: "secondary", size: "sm" })}
            href={getArtifactDownloadUrl(artifact)}
            download
          >
            <Download />
            Download
          </a>
        </div>
      </div>
      {isPreviewOpen && <ArtifactPreview artifact={artifact} previewUrl={previewUrl} />}
    </article>
  );
}

export function ArtifactPreview({
  artifact,
  previewUrl,
}: {
  artifact: Artifact;
  previewUrl: string;
}) {
  const contentType = artifact.content_type ?? "";

  if (contentType.startsWith("video/")) {
    return (
      <video
        className="max-h-96 w-full rounded-xl bg-black"
        controls
        preload="metadata"
        src={previewUrl}
      >
        <a href={previewUrl} target="_blank" rel="noreferrer">
          Open video preview
        </a>
      </video>
    );
  }

  if (contentType.startsWith("audio/")) {
    return <audio className="w-full" controls preload="metadata" src={previewUrl} />;
  }

  if (contentType.startsWith("image/")) {
    return (
      <img
        alt={`${artifact.artifact_type} preview`}
        className="max-h-96 w-full rounded-xl object-contain"
        src={previewUrl}
      />
    );
  }

  return (
    <iframe
      className="h-96 w-full rounded-xl border bg-white"
      src={previewUrl}
      title={`${artifact.artifact_type} preview`}
    />
  );
}

export function ProviderRequestRow({ request }: { request: ProviderRequest }) {
  return (
    <article className="flex flex-col justify-between gap-4 rounded-2xl border bg-slate-50 p-4 sm:flex-row sm:items-center">
      <div>
        <strong>{request.provider_name}</strong>
        <p className="mt-1 break-all text-sm text-muted-foreground">
          {request.provider_request_id}
        </p>
        {request.last_error && (
          <p className="mt-1 break-all text-sm font-medium text-destructive">
            {request.last_error}
          </p>
        )}
      </div>
      <Badge variant="secondary">{request.status}</Badge>
    </article>
  );
}
