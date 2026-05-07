import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  AlertCircle,
  Download,
  ExternalLink,
  Loader2,
  Plug,
  PlugZap,
  RefreshCw,
} from "lucide-react";

import { uploadPlatformOptions } from "../constants/uploadPlatforms";
import type { AppPage } from "../interfaces/navigation";
import { formatDate, getErrorMessage } from "../lib/format";

import type {
  Artifact,
  ConnectedAccount,
  Job,
  JobEventPayload,
  ProviderRequest,
  PublishUploadResponse,
  UploadPlatform,
} from "../interfaces/job";
import {
  apiBaseUrl,
  createJob,
  deleteConnectedAccount,
  getArtifactDownloadUrl,
  getArtifactPreviewUrl,
  getArtifacts,
  getConnectedAccounts,
  getJob,
  getJobs,
  getProviderRequests,
  getYouTubeAuthorizeUrl,
  publishJobUpload,
  uploadSourceVideo,
} from "../services/api";
import { subscribeToJobEvents } from "../services/jobEvents";
import { EmptyState } from "./common/EmptyState";
import { Sidebar } from "./layout/Sidebar";
import { ConnectorDraft } from "./pages/ConnectorDraft";
import { VideosDraft } from "./pages/VideosDraft";
import { Alert, AlertDescription, AlertTitle } from "./ui/alert";
import { Badge } from "./ui/badge";
import { Button, buttonVariants } from "./ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/card";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Progress } from "./ui/progress";
import { cn } from "../lib/utils";

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

const COMPLETED_JOBS_PAGE_SIZE = 10;

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 2_500,
      retry: 1,
    },
  },
});

export function AppProvider() {
  return (
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  );
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

function App() {
  const [activePage, setActivePage] = useState<AppPage>("dashboard");
  const [completedJobsPage, setCompletedJobsPage] = useState(0);
  const [sourceLanguage, setSourceLanguage] = useState("zh");
  const [targetLanguage, setTargetLanguage] = useState("vi");
  const [file, setFile] = useState<File | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(() =>
    getJobIdFromUrl(),
  );
  const [jobIdInput, setJobIdInput] = useState(() => {
    const initialJobId = getJobIdFromUrl();
    return initialJobId === null ? "" : String(initialJobId);
  });
  const [formError, setFormError] = useState<string | null>(null);
  const [publishPlatform, setPublishPlatform] =
    useState<UploadPlatform>("youtube");
  const [publishTitle, setPublishTitle] = useState("");
  const [publishDescription, setPublishDescription] = useState("");
  const [publishPrivacy, setPublishPrivacy] = useState("public");
  const [selectedConnectedAccountId, setSelectedConnectedAccountId] = useState<
    number | null
  >(null);
  const [publishResult, setPublishResult] =
    useState<PublishUploadResponse | null>(null);
  const [publishError, setPublishError] = useState<string | null>(null);
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

  const connectedAccountsQuery = useQuery({
    queryKey: ["connected-accounts", publishPlatform],
    queryFn: () => getConnectedAccounts(publishPlatform),
  });

  const youtubeConnectedAccountsQuery = useQuery({
    queryKey: ["connected-accounts", "youtube", "videos"],
    queryFn: () => getConnectedAccounts("youtube"),
  });

  const completedJobsQuery = useQuery({
    queryKey: ["jobs", "completed", completedJobsPage],
    queryFn: () =>
      getJobs({
        status: "completed",
        limit: COMPLETED_JOBS_PAGE_SIZE,
        offset: completedJobsPage * COMPLETED_JOBS_PAGE_SIZE,
      }),
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

  useEffect(() => {
    setPublishTitle("");
    setPublishDescription("");
    setPublishPrivacy("public");
    setPublishResult(null);
    setPublishError(null);
  }, [selectedJobId]);

  const createAndUploadMutation = useMutation({
    mutationFn: async () => {
      if (!file) {
        throw new Error("Choose a source video before creating a job.");
      }

      const created = await createJob(sourceLanguage, targetLanguage);
      return uploadSourceVideo(created.id, file);
    },
    onSuccess: async (uploaded) => {
      setFormError(null);
      setSelectedJobId(uploaded.id);
      setJobIdInput(String(uploaded.id));
      queryClient.setQueryData(["job", uploaded.id], uploaded);
      await refreshDashboard(uploaded.id);
    },
    onError: (error) => {
      setFormError(
        getErrorMessage(error, "Unable to create and upload the job."),
      );
    },
  });

  const quickPublishMutation = useMutation({
    mutationFn: async ({
      jobId,
      platform,
    }: {
      jobId: number;
      platform: UploadPlatform;
    }) => {
      const accountId =
        platform === "youtube" ? youtubeConnectedAccounts[0]?.id ?? null : null;

      return publishJobUpload(jobId, {
        platform,
        connected_account_id: accountId,
        title: `Dubbed video job #${jobId}`,
        description: "Published from the AI Lab videos dashboard.",
        privacy: "public",
      });
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({
        queryKey: ["provider-requests", result.job_id],
      });
    },
  });

  const publishUploadMutation = useMutation({
    mutationFn: async () => {
      if (!job) {
        throw new Error("Load a completed job before publishing.");
      }
      if (job.status !== "completed") {
        throw new Error("Job must be completed before publishing.");
      }
      if (!publishTitle.trim()) {
        throw new Error("Enter a publish title.");
      }

      return publishJobUpload(job.id, {
        platform: publishPlatform,
        connected_account_id:
          publishPlatform === "youtube" ? selectedConnectedAccountId : null,
        title: publishTitle.trim(),
        description: publishDescription.trim(),
        privacy: publishPrivacy.trim() || "public",
      });
    },
    onSuccess: async (result) => {
      setPublishError(null);
      setPublishResult(result);
      await queryClient.invalidateQueries({
        queryKey: ["provider-requests", result.job_id],
      });
    },
    onError: (error) => {
      setPublishResult(null);
      setPublishError(
        getErrorMessage(error, "Unable to publish the completed video."),
      );
    },
  });

  const job = jobQuery.data ?? null;
  const artifacts = artifactsQuery.data ?? [];
  const providerRequests = providerRequestsQuery.data ?? [];
  const connectedAccounts = connectedAccountsQuery.data ?? [];
  const youtubeConnectedAccounts = youtubeConnectedAccountsQuery.data ?? [];
  const completedJobsResponse = completedJobsQuery.data ?? null;
  const completedJobs = completedJobsResponse?.items ?? [];
  const completedJobsTotal = completedJobsResponse?.total ?? 0;
  const completedJobsTotalPages = Math.max(
    1,
    Math.ceil(completedJobsTotal / COMPLETED_JOBS_PAGE_SIZE),
  );
  const completedJobProviderRequests = useQueries({
    queries: completedJobs.map((completedJob) => ({
      queryKey: ["provider-requests", completedJob.id],
      queryFn: () => getProviderRequests(completedJob.id),
      staleTime: 2_500,
    })),
  });
  const completedProviderRequestsByJobId = useMemo(() => {
    const requestsByJobId = new Map<number, ProviderRequest[]>();
    completedJobs.forEach((completedJob, index) => {
      requestsByJobId.set(
        completedJob.id,
        completedJobProviderRequests[index]?.data ?? [],
      );
    });
    return requestsByJobId;
  }, [completedJobs, completedJobProviderRequests]);
  const isVideosLoading =
    completedJobsQuery.isLoading ||
    completedJobProviderRequests.some((query) => query.isLoading);
  const videosError =
    completedJobsQuery.error ??
    completedJobProviderRequests.find((query) => query.error)?.error ??
    youtubeConnectedAccountsQuery.error;
  const isRefreshing =
    jobQuery.isFetching ||
    artifactsQuery.isFetching ||
    providerRequestsQuery.isFetching ||
    connectedAccountsQuery.isFetching ||
    youtubeConnectedAccountsQuery.isFetching;
  const isLoadingJob =
    jobQuery.isLoading ||
    artifactsQuery.isLoading ||
    providerRequestsQuery.isLoading;
  const dashboardError =
    jobQuery.error ??
    artifactsQuery.error ??
    providerRequestsQuery.error ??
    connectedAccountsQuery.error;
  const error =
    formError ??
    (dashboardError
      ? getErrorMessage(dashboardError, "Unable to refresh the dashboard.")
      : null);

  const activeStepIndex = useMemo(() => {
    if (!job) return -1;
    return statusOrder.indexOf(job.status);
  }, [job]);

  const finalDubbedVideo = useMemo(
    () =>
      artifacts.find((artifact) => artifact.artifact_type === "dubbed_video"),
    [artifacts],
  );

  useEffect(() => {
    if (selectedConnectedAccountId !== null) {
      const stillExists = connectedAccounts.some(
        (account) => account.id === selectedConnectedAccountId,
      );
      if (stillExists) return;
    }
    setSelectedConnectedAccountId(connectedAccounts[0]?.id ?? null);
  }, [connectedAccounts, selectedConnectedAccountId]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connectedAccountId = Number(params.get("youtube_connected"));
    if (!Number.isInteger(connectedAccountId) || connectedAccountId <= 0)
      return;

    setPublishPlatform("youtube");
    setSelectedConnectedAccountId(connectedAccountId);
    params.delete("youtube_connected");
    const nextSearch = params.toString();
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ""}${window.location.hash}`,
    );
    void queryClient.invalidateQueries({
      queryKey: ["connected-accounts", "youtube"],
    });
  }, [queryClient]);

  async function refreshDashboard(jobId = selectedJobId) {
    if (!jobId) return;

    setFormError(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
      queryClient.invalidateQueries({ queryKey: ["artifacts", jobId] }),
      queryClient.invalidateQueries({ queryKey: ["provider-requests", jobId] }),
      queryClient.invalidateQueries({
        queryKey: ["connected-accounts", publishPlatform],
      }),
      queryClient.invalidateQueries({ queryKey: ["jobs", "completed"] }),
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

  function handleConnectYouTube() {
    window.location.href = getYouTubeAuthorizeUrl();
  }

  async function handleDisconnectAccount(account: ConnectedAccount) {
    await deleteConnectedAccount(account.id);
    if (selectedConnectedAccountId === account.id) {
      setSelectedConnectedAccountId(null);
    }
    await queryClient.invalidateQueries({
      queryKey: ["connected-accounts", account.platform],
    });
  }

  function handlePublishUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    publishUploadMutation.mutate();
  }

  return (
    <div className="min-h-screen bg-background lg:grid lg:grid-cols-[17rem_minmax(0,1fr)]">
      <Sidebar activePage={activePage} onPageChange={setActivePage} />
      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-10">
        {activePage === "dashboard" && (
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
            Create a pipeline job, upload source video, watch websocket status
            updates, and inspect the generated artifacts and provider requests
            from one Tailwind + shadcn/ui client-side app.
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

      {Boolean(error) && (
        <Alert variant="destructive" className="mb-6 bg-red-50">
          <AlertCircle />
          <AlertTitle>Dashboard error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <section className="mb-6 grid gap-6 lg:grid-cols-2">
        <Card className="bg-white/90 shadow-xl shadow-slate-900/5">
          <CardHeader className="grid-cols-[auto_1fr] items-center">
            <span className="flex size-10 items-center justify-center rounded-full bg-primary/10 text-lg font-black text-primary">
              1
            </span>
            <div>
              <CardTitle>Create pipeline job</CardTitle>
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
                <Input
                  id="target-language"
                  value={targetLanguage}
                  onChange={(event) => setTargetLanguage(event.target.value)}
                />
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
                  : "Create job and upload video"}
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

      <Card className="mb-6 bg-white/90 shadow-xl shadow-slate-900/5">
        <CardHeader>
          <div>
            <CardDescription className="font-black uppercase tracking-[0.18em] text-primary">
              Final preview
            </CardDescription>
            <CardTitle className="mt-2 text-2xl">Dubbed video</CardTitle>
          </div>
          <CardAction>
            {finalDubbedVideo && (
              <a
                className={buttonVariants({ size: "sm" })}
                href={getArtifactDownloadUrl(finalDubbedVideo)}
                download
              >
                <Download />
                Download video
              </a>
            )}
          </CardAction>
        </CardHeader>
        <CardContent>
          {finalDubbedVideo ? (
            <video
              className="block aspect-video max-h-[68vh] w-full rounded-2xl bg-slate-950 object-contain"
              controls
              preload="metadata"
              src={getArtifactPreviewUrl(finalDubbedVideo)}
            >
              <track kind="captions" />
              Your browser does not support video previews.
            </video>
          ) : (
            <EmptyState>
              The final dubbed video preview appears here after processing
              completes.
            </EmptyState>
          )}
        </CardContent>
      </Card>

      <Card className="mb-6 bg-white/90 shadow-xl shadow-slate-900/5">
        <CardHeader>
          <div>
            <CardDescription className="font-black uppercase tracking-[0.18em] text-primary">
              Publish
            </CardDescription>
            <CardTitle className="mt-2 text-2xl">
              Upload completed video
            </CardTitle>
            <CardDescription>
              Send the completed dubbed artifact to YouTube, Facebook, or TikTok
              through the Core API upload adapter.
            </CardDescription>
          </div>
          <CardAction>
            {job?.status === "completed" ? (
              <Badge className="bg-emerald-100 text-emerald-700">Ready</Badge>
            ) : (
              <Badge variant="secondary">Waiting for completed job</Badge>
            )}
          </CardAction>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={handlePublishUpload}>
            <div className="grid gap-3 md:grid-cols-3">
              {uploadPlatformOptions.map((platform) => (
                <button
                  key={platform.value}
                  type="button"
                  className={cn(
                    "rounded-2xl border bg-slate-50 p-4 text-left transition hover:border-primary/40 hover:bg-primary/5",
                    publishPlatform === platform.value &&
                      "border-primary bg-primary/10 ring-2 ring-primary/20",
                  )}
                  onClick={() => setPublishPlatform(platform.value)}
                >
                  <span className="font-black">{platform.label}</span>
                  <span className="mt-1 block text-sm text-muted-foreground">
                    {platform.description}
                  </span>
                </button>
              ))}
            </div>
            {publishPlatform === "youtube" && (
              <div className="rounded-2xl border bg-slate-50 p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <Label>YouTube connector</Label>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Connect a Google account with the YouTube upload scope,
                      then choose it for this publish.
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={handleConnectYouTube}
                  >
                    Connect YouTube
                  </Button>
                </div>
                <div className="mt-4 grid gap-2">
                  {connectedAccounts.length > 0 ? (
                    connectedAccounts.map((account) => (
                      <label
                        key={account.id}
                        className={cn(
                          "flex cursor-pointer flex-col gap-3 rounded-xl border bg-white p-3 text-sm sm:flex-row sm:items-center sm:justify-between",
                          selectedConnectedAccountId === account.id &&
                            "border-primary ring-2 ring-primary/20",
                        )}
                      >
                        <span className="flex items-start gap-3">
                          <input
                            className="mt-1"
                            type="radio"
                            name="connected-youtube-account"
                            checked={selectedConnectedAccountId === account.id}
                            onChange={() =>
                              setSelectedConnectedAccountId(account.id)
                            }
                          />
                          <span>
                            <strong>{account.display_name}</strong>
                            <span className="mt-1 block break-all text-muted-foreground">
                              Account #{account.id} · scopes:{" "}
                              {account.scopes || "unknown"}
                            </span>
                            {account.expires_at && (
                              <span className="mt-1 block text-muted-foreground">
                                Access token expires{" "}
                                {formatDate(account.expires_at)}
                              </span>
                            )}
                          </span>
                        </span>
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          onClick={(event) => {
                            event.preventDefault();
                            void handleDisconnectAccount(account);
                          }}
                        >
                          Disconnect
                        </Button>
                      </label>
                    ))
                  ) : (
                    <p className="rounded-xl border border-dashed bg-white p-3 text-sm text-muted-foreground">
                      No YouTube account connected yet. Publishing can still use
                      env credentials if configured.
                    </p>
                  )}
                </div>
              </div>
            )}

            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_12rem]">
              <div className="grid gap-2">
                <Label htmlFor="publish-title">Title</Label>
                <Input
                  id="publish-title"
                  maxLength={150}
                  placeholder="Dubbed video title"
                  value={publishTitle}
                  onChange={(event) => setPublishTitle(event.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="publish-privacy">Privacy</Label>
                <Input
                  id="publish-privacy"
                  placeholder="public"
                  value={publishPrivacy}
                  onChange={(event) => setPublishPrivacy(event.target.value)}
                />
              </div>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="publish-description">Description</Label>
              <textarea
                id="publish-description"
                className="min-h-24 rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none transition-[color,box-shadow] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                maxLength={5000}
                placeholder="Optional platform description"
                value={publishDescription}
                onChange={(event) => setPublishDescription(event.target.value)}
              />
            </div>
            {publishError && (
              <p className="text-sm font-medium text-destructive">
                {publishError}
              </p>
            )}
            {publishResult && (
              <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
                <strong>Published to {publishResult.platform}.</strong>
                <p className="mt-1 break-all">
                  Provider request: {publishResult.provider_request_id}
                </p>
                {publishResult.remote_url && (
                  <a
                    className="mt-2 inline-flex items-center gap-2 font-bold text-emerald-800 underline"
                    href={publishResult.remote_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open published video
                    <ExternalLink className="size-4" />
                  </a>
                )}
              </div>
            )}
            <Button
              type="submit"
              size="lg"
              disabled={
                !finalDubbedVideo ||
                job?.status !== "completed" ||
                publishUploadMutation.isPending
              }
            >
              {publishUploadMutation.isPending && (
                <Loader2 className="animate-spin" />
              )}
              {publishUploadMutation.isPending
                ? "Publishing…"
                : `Publish to ${uploadPlatformOptions.find((platform) => platform.value === publishPlatform)?.label}`}
            </Button>
          </form>
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
        )}

        {activePage === "connector" && <ConnectorDraft apiBaseUrl={apiBaseUrl} />}

        {activePage === "videos" && (
          <VideosDraft
            completedJobs={completedJobs}
            error={videosError}
            isLoading={isVideosLoading}
            onPageChange={setCompletedJobsPage}
            onPublish={(jobId, platform) =>
              quickPublishMutation.mutate({ jobId, platform })
            }
            page={completedJobsPage}
            pageSize={COMPLETED_JOBS_PAGE_SIZE}
            pendingPublish={
              quickPublishMutation.isPending
                ? quickPublishMutation.variables ?? null
                : null
            }
            providerRequestsByJobId={completedProviderRequestsByJobId}
            publishError={quickPublishMutation.error}
            total={completedJobsTotal}
            totalPages={completedJobsTotalPages}
          />
        )}
      </main>
    </div>
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
