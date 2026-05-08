import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  ExternalLink,
  Loader2,
  Plug,
  PlugZap,
  RefreshCw,
} from "lucide-react";

import {
  DEFAULT_TARGET_LANGUAGE_CODE,
  targetLanguages,
} from "../../constants/languages";
import { formatDate, getErrorMessage } from "../../lib/format";
import { useErrorToast } from "../../hooks/useErrorToast";
import { cn } from "../../lib/utils";
import type {
  Artifact,
  Job,
  JobEventPayload,
  ProviderRequest,
} from "../../interfaces/job";
import {
  apiBaseUrl,
  createVideoCollection,
  getArtifactDownloadUrl,
  getArtifactPreviewUrl,
  getArtifacts,
  getDubProviderVoices,
  getJob,
  getProviderRequests,
  uploadVideoCollectionSource,
} from "../../services/api";
import { subscribeToJobEvents } from "../../services/jobEvents";
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
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Progress } from "../ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";

const statusLabels: Record<Job["status"], string> = {
  created: "Created",
  uploaded: "Uploaded",
  processing: "Processing",
  waiting_provider: "Waiting provider",
  finalizing: "Finalizing",
  completed: "Completed",
  failed: "Failed",
  canceled: "Canceled",
};

const statusOrder: Job["status"][] = [
  "created",
  "uploaded",
  "processing",
  "waiting_provider",
  "finalizing",
  "completed",
];

const defaultVoiceValue = "__provider_default__";

function formatVoiceLabel(voice: { name: string; credit_factor?: number | null }) {
  return voice.credit_factor && voice.credit_factor > 1
    ? `${voice.name} x${voice.credit_factor}`
    : voice.name;
}

function getJobIdFromUrl() {
  const rawJobId = new URLSearchParams(window.location.search).get("jobId");
  if (!rawJobId) return null;

  const parsedJobId = Number(rawJobId);
  return Number.isInteger(parsedJobId) && parsedJobId > 0 ? parsedJobId : null;
}

function setJobIdInUrl(jobId: number | null) {
  const url = new URL(window.location.href);

  if (jobId === null) {
    url.searchParams.delete("jobId");
  } else {
    url.searchParams.set("jobId", String(jobId));
  }

  window.history.replaceState(
    null,
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
}

export default function DashboardPage() {
  const [sourceLanguage, setSourceLanguage] = useState("zh");
  const [targetLanguage, setTargetLanguage] = useState(
    DEFAULT_TARGET_LANGUAGE_CODE,
  );
  const [voiceId, setVoiceId] = useState("");
  const [outputVideoSpeed, setOutputVideoSpeed] = useState("1");
  const [originalAudioVolume, setOriginalAudioVolume] = useState("0.15");
  const [file, setFile] = useState<File | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(() =>
    getJobIdFromUrl(),
  );
  const [jobIdInput, setJobIdInput] = useState(() => {
    const initialJobId = getJobIdFromUrl();
    return initialJobId === null ? "" : String(initialJobId);
  });
  const [formError, setFormError] = useState<string | null>(null);
  const [socketStatus, setSocketStatus] = useState<
    "idle" | "connected" | "disconnected" | "error"
  >("idle");
  const queryClient = useQueryClient();

  const jobQuery = useQuery({
    queryKey: ["job", selectedJobId],
    queryFn: () => getJob(selectedJobId!),
    enabled: selectedJobId !== null,
  });

  const artifactsQuery = useQuery({
    queryKey: ["artifacts", selectedJobId],
    queryFn: () => getArtifacts(selectedJobId!),
    enabled: selectedJobId !== null,
  });

  const providerRequestsQuery = useQuery({
    queryKey: ["provider-requests", selectedJobId],
    queryFn: () => getProviderRequests(selectedJobId!),
    enabled: selectedJobId !== null,
  });

  const voicesQuery = useQuery({
    queryKey: ["dub-provider-voices", targetLanguage],
    queryFn: () => getDubProviderVoices(false, targetLanguage),
    staleTime: 24 * 60 * 60 * 1000,
  });

  useEffect(() => {
    setJobIdInUrl(selectedJobId);
  }, [selectedJobId]);

  useEffect(() => {
    function handlePopState() {
      const jobIdFromUrl = getJobIdFromUrl();
      setSelectedJobId(jobIdFromUrl);
      setJobIdInput(jobIdFromUrl === null ? "" : String(jobIdFromUrl));
    }

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (selectedJobId === null) {
      setSocketStatus("idle");
      return undefined;
    }

    return subscribeToJobEvents(selectedJobId, {
      onOpen: () => setSocketStatus("connected"),
      onError: () => setSocketStatus("error"),
      onClose: () => setSocketStatus("disconnected"),
      onMessage: (payload: JobEventPayload) => {
        if (payload.job) {
          queryClient.setQueryData(["job", selectedJobId], payload.job);
        }
        if (payload.artifacts) {
          queryClient.setQueryData(
            ["artifacts", selectedJobId],
            payload.artifacts,
          );
        }
        if (payload.provider_requests) {
          queryClient.setQueryData(
            ["provider-requests", selectedJobId],
            payload.provider_requests,
          );
        }
      },
    });
  }, [queryClient, selectedJobId]);

  const refreshVoicesMutation = useMutation({
    mutationFn: () => getDubProviderVoices(true, targetLanguage),
    onSuccess: (voiceList) => {
      queryClient.setQueryData(
        ["dub-provider-voices", targetLanguage],
        voiceList,
      );
    },
  });

  const createAndUploadMutation = useMutation({
    mutationFn: async () => {
      if (!file) {
        throw new Error("Choose a source video before creating a collection.");
      }

      const parsedOutputVideoSpeed = Number(outputVideoSpeed);
      if (!Number.isFinite(parsedOutputVideoSpeed) || parsedOutputVideoSpeed <= 0 || parsedOutputVideoSpeed > 4) {
        throw new Error("Output video speed must be greater than 0 and no more than 4.");
      }

      const parsedOriginalAudioVolume = Number(originalAudioVolume);
      if (
        !Number.isFinite(parsedOriginalAudioVolume) ||
        parsedOriginalAudioVolume < 0 ||
        parsedOriginalAudioVolume > 1
      ) {
        throw new Error("Original audio volume must be between 0 and 1.");
      }

      const collection = await createVideoCollection({
        source_language: sourceLanguage,
        target_language: targetLanguage,
        title: file.name,
        voice_id: voiceId || null,
        output_video_speed: parsedOutputVideoSpeed,
        original_audio_volume: parsedOriginalAudioVolume,
        split_threshold_seconds: 60,
      });
      return uploadVideoCollectionSource(collection.id, file);
    },
    onSuccess: async (uploadedCollection) => {
      const firstSegment = uploadedCollection.segments[0];
      const uploaded = firstSegment?.job ?? null;
      if (!uploaded) {
        throw new Error(
          "Collection upload did not create a trackable segment job.",
        );
      }
      setFormError(null);
      setSelectedJobId(uploaded.id);
      setJobIdInput(String(uploaded.id));
      queryClient.setQueryData(["job", uploaded.id], uploaded);
      await queryClient.invalidateQueries({ queryKey: ["video-collections"] });
      await refreshDashboard(uploaded.id);
    },
    onError: (error) => {
      setFormError(
        getErrorMessage(
          error,
          "Unable to create the collection and upload the video.",
        ),
      );
    },
  });

  const job = jobQuery.data ?? null;
  const artifacts = artifactsQuery.data ?? [];
  const providerRequests = providerRequestsQuery.data ?? [];
  const voices = voicesQuery.data?.items ?? [];
  const selectedVoice = voices.find((voice) => voice.voice_id === voiceId) ?? null;
  const isRefreshing =
    jobQuery.isFetching ||
    artifactsQuery.isFetching ||
    providerRequestsQuery.isFetching;
  const isLoadingJob =
    jobQuery.isLoading ||
    artifactsQuery.isLoading ||
    providerRequestsQuery.isLoading;
  const dashboardError =
    jobQuery.error ?? artifactsQuery.error ?? providerRequestsQuery.error;
  const error =
    formError ??
    (dashboardError
      ? getErrorMessage(dashboardError, "Unable to refresh the dashboard.")
      : null);

  useErrorToast(error, "Dashboard error");

  const activeStepIndex = useMemo(() => {
    if (!job) return -1;
    return statusOrder.indexOf(job.status);
  }, [job]);

  async function refreshDashboard(jobId = selectedJobId) {
    if (!jobId) return;

    setFormError(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
      queryClient.invalidateQueries({ queryKey: ["artifacts", jobId] }),
      queryClient.invalidateQueries({ queryKey: ["provider-requests", jobId] }),
    ]);
  }

  function handleCreateAndUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    createAndUploadMutation.mutate();
  }

  function handleLoadExisting(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsedId = Number(jobIdInput);
    if (!Number.isInteger(parsedId) || parsedId <= 0) {
      setFormError("Enter a valid numeric job ID.");
      return;
    }

    setFormError(null);
    setSelectedJobId(parsedId);
  }

  return (
    <>
      <section className="mb-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-end">
        <div>
          <p className="text-sm font-black uppercase tracking-[0.24em] text-primary">
            AI Lab Dubbing Pipeline
          </p>
          <h1 className="mt-3 max-w-5xl text-5xl font-black leading-none tracking-[-0.07em] text-slate-950 sm:text-7xl lg:text-8xl">
            AI Lab
          </h1>
          <p className="mt-6 max-w-3xl text-lg leading-8 text-muted-foreground">
            Create a video collection, upload source video, watch websocket
            status updates, and inspect the generated artifacts and provider
            requests from one Tailwind + shadcn/ui client-side app.
          </p>
        </div>
        <Card className="border-primary/10 bg-white/80 shadow-xl shadow-slate-900/5 backdrop-blur">
          <CardHeader>
            <CardDescription>Connected API</CardDescription>
            <CardTitle className="break-all text-lg">{apiBaseUrl}</CardTitle>
            <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
              {socketStatus === "connected" ? (
                <PlugZap className="size-4 text-emerald-600" />
              ) : (
                <Plug className="size-4" />
              )}
              <span>Websocket {socketStatus}</span>
            </div>
          </CardHeader>
        </Card>
      </section>

      <section className="mb-6 grid gap-6 lg:grid-cols-2">
        <Card className="bg-white/90 shadow-xl shadow-slate-900/5">
          <CardHeader className="grid-cols-[auto_1fr] items-center">
            <span className="flex size-10 items-center justify-center rounded-full bg-primary/10 text-lg font-black text-primary">
              1
            </span>
            <div>
              <CardTitle>Create video collection</CardTitle>
              <CardDescription>
                Defaults match the current ZH → VI dubbing workflow.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <form className="grid gap-4" onSubmit={handleCreateAndUpload}>
              <div className="grid gap-2">
                <Label htmlFor="source-language">Source language</Label>
                <Input
                  id="source-language"
                  value={sourceLanguage}
                  onChange={(event) => setSourceLanguage(event.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="target-language">Target language</Label>
                <Select
                  value={targetLanguage}
                  onValueChange={(value) => {
                    setTargetLanguage(value);
                    setVoiceId("");
                  }}
                >
                  <SelectTrigger id="target-language">
                    <SelectValue placeholder="Select target language" />
                  </SelectTrigger>
                  <SelectContent>
                    {targetLanguages.map((language) => (
                      <SelectItem key={language.code} value={language.code}>
                        {language.name} ({language.code})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="voice-id">Voice</Label>
                <Select
                  value={voiceId || defaultVoiceValue}
                  disabled={voicesQuery.isLoading}
                  onValueChange={(value) =>
                    setVoiceId(value === defaultVoiceValue ? "" : value)
                  }
                >
                  <SelectTrigger id="voice-id">
                    <SelectValue placeholder="Default provider voice" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={defaultVoiceValue}>
                      Default provider voice
                    </SelectItem>
                    {voices.map((voice) => (
                      <SelectItem key={voice.voice_id} value={voice.voice_id}>
                        {formatVoiceLabel(voice)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedVoice && (
                  <div className="grid gap-2 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
                    <div className="flex flex-wrap gap-x-3 gap-y-1">
                      <span className="font-medium text-foreground">
                        {formatVoiceLabel(selectedVoice)}
                      </span>
                      <span className="break-all">Code: {selectedVoice.voice_id}</span>
                      {selectedVoice.credit_factor && selectedVoice.credit_factor > 1 ? (
                        <span>Credit factor: x{selectedVoice.credit_factor}</span>
                      ) : null}
                    </div>
                    {selectedVoice.demo ? (
                      <audio
                        className="h-9 w-full"
                        controls
                        preload="none"
                        src={selectedVoice.demo}
                      >
                        <a href={selectedVoice.demo} target="_blank" rel="noreferrer">
                          Open voice demo
                        </a>
                      </audio>
                    ) : (
                      <span>No demo preview is available for this voice.</span>
                    )}
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>
                    {voicesQuery.isLoading
                      ? "Loading provider voices…"
                      : voicesQuery.isError
                        ? "Unable to load provider voices; default voice will be used."
                        : `${voices.length} provider voices available${
                            voicesQuery.data?.cached ? " from cache" : ""
                          }.`}
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    disabled={voicesQuery.isFetching || refreshVoicesMutation.isPending}
                    onClick={() => refreshVoicesMutation.mutate()}
                  >
                    {(voicesQuery.isFetching || refreshVoicesMutation.isPending) && (
                      <Loader2 className="animate-spin" />
                    )}
                    Refresh voices
                  </Button>
                </div>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <Label htmlFor="output-video-speed">Output video speed</Label>
                  <Input
                    id="output-video-speed"
                    type="number"
                    min="0.1"
                    max="4"
                    step="0.05"
                    value={outputVideoSpeed}
                    onChange={(event) => setOutputVideoSpeed(event.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Applied only during final muxing; default is 1x.
                  </p>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="original-audio-volume">Original audio volume</Label>
                  <Input
                    id="original-audio-volume"
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    value={originalAudioVolume}
                    onChange={(event) => setOriginalAudioVolume(event.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Mixed under the dub at the final step; default is 0.15.
                  </p>
                </div>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="source-video">Source video</Label>
                <Input
                  id="source-video"
                  type="file"
                  accept="video/*"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />
              </div>
              <Button
                type="submit"
                size="lg"
                disabled={createAndUploadMutation.isPending}
              >
                {createAndUploadMutation.isPending && (
                  <Loader2 className="animate-spin" />
                )}
                {createAndUploadMutation.isPending
                  ? "Creating and uploading…"
                  : "Create collection and upload video"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card className="bg-white/90 shadow-xl shadow-slate-900/5">
          <CardHeader className="grid-cols-[auto_1fr] items-center">
            <span className="flex size-10 items-center justify-center rounded-full bg-primary/10 text-lg font-black text-primary">
              2
            </span>
            <div>
              <CardTitle>Open existing job</CardTitle>
              <CardDescription>
                Use a job ID from Swagger, logs, or a previous dashboard
                session.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <form className="grid gap-4" onSubmit={handleLoadExisting}>
              <div className="grid gap-2">
                <Label htmlFor="job-id">Job ID</Label>
                <Input
                  id="job-id"
                  inputMode="numeric"
                  placeholder="Example: 1"
                  value={jobIdInput}
                  onChange={(event) => setJobIdInput(event.target.value)}
                />
              </div>
              <Button type="submit" size="lg" disabled={isLoadingJob}>
                {isLoadingJob && <Loader2 className="animate-spin" />}
                {isLoadingJob ? "Loading…" : "Load job"}
              </Button>
              {job && (
                <Button
                  variant="secondary"
                  type="button"
                  onClick={() => refreshDashboard(job.id)}
                  disabled={isRefreshing}
                >
                  <RefreshCw className={cn(isRefreshing && "animate-spin")} />
                  Refresh now
                </Button>
              )}
              {job?.status === "completed" && (
                <Link
                  className={buttonVariants({
                    variant: "secondary",
                    size: "lg",
                  })}
                  to={`/publish?jobId=${job.id}`}
                >
                  Publish this job
                </Link>
              )}
            </form>
          </CardContent>
        </Card>
      </section>

      <Card className="mb-6 bg-white/90 shadow-xl shadow-slate-900/5">
        <CardHeader>
          <div>
            <CardDescription className="font-black uppercase tracking-[0.18em] text-primary">
              Pipeline status
            </CardDescription>
            <CardTitle className="mt-2 text-2xl">
              {job
                ? `Job #${job.id} · ${job.external_job_id}`
                : "No job loaded"}
            </CardTitle>
          </div>
          <CardAction>
            {job && (
              <StatusBadge status={job.status}>
                {statusLabels[job.status]}
              </StatusBadge>
            )}
          </CardAction>
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
                <Badge variant="secondary">
                  Voice {job.voice_id || "provider default"}
                </Badge>
                <Badge variant="secondary">
                  Speed {job.output_video_speed}x
                </Badge>
                <Badge variant="secondary">
                  Original volume {job.original_audio_volume}
                </Badge>
                <Badge variant="secondary">
                  {job.progress_percent}% complete
                </Badge>
                <Badge variant="secondary">
                  Updated {formatDate(job.updated_at)}
                </Badge>
                <Badge variant="secondary">
                  {job.current_step ?? "Waiting for next step"}
                </Badge>
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
    </>
  );
}

function StatusBadge({
  status,
  children,
}: {
  status: Job["status"];
  children: React.ReactNode;
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

function DataPanel({
  title,
  count,
  emptyLabel,
  children,
}: {
  title: string;
  count: number;
  emptyLabel: string;
  children: React.ReactNode;
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

function ArtifactRow({ artifact }: { artifact: Artifact }) {
  return (
    <article className="flex flex-col justify-between gap-4 rounded-2xl border bg-slate-50 p-4 sm:flex-row sm:items-center">
      <div>
        <strong>{artifact.artifact_type}</strong>
        <p className="mt-1 break-all text-sm text-muted-foreground">
          {artifact.content_type ?? "Unknown content type"}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <a
          className={buttonVariants({ variant: "secondary", size: "sm" })}
          href={getArtifactDownloadUrl(artifact)}
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
    </article>
  );
}

function ProviderRequestRow({ request }: { request: ProviderRequest }) {
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
