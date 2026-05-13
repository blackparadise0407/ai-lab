import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plug, PlugZap } from "lucide-react";

import {
  DEFAULT_TARGET_LANGUAGE_CODE,
  targetLanguages,
} from "../../constants/languages";
import { getErrorMessage } from "../../lib/format";
import { useErrorToast } from "../../hooks/useErrorToast";
import type { Job, JobEventPayload } from "../../interfaces/job";
import {
  apiBaseUrl,
  createVideoCollection,
  getDubProviderVoices,
  getJob,
  getJobs,
  uploadVideoCollectionSource,
} from "../../services/api";
import { subscribeToJobEvents } from "../../services/jobEvents";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../ui/card";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import { JobStatusCard } from "./job-detail-ui";

const defaultVoiceValue = "__provider_default__";

const runningJobStatuses = new Set<Job["status"]>([
  "created",
  "uploaded",
  "processing",
  "waiting_provider",
  "finalizing",
]);

export default function DashboardPage() {
  const [sourceLanguage, setSourceLanguage] = useState("zh");
  const [targetLanguage, setTargetLanguage] = useState(
    DEFAULT_TARGET_LANGUAGE_CODE,
  );
  const [translationContext, setTranslationContext] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [outputVideoSpeed, setOutputVideoSpeed] = useState("1");
  const [originalAudioVolume, setOriginalAudioVolume] = useState("0.15");
  const [file, setFile] = useState<File | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
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

  const activeJobsQuery = useQuery({
    queryKey: ["jobs", "running"],
    queryFn: () => getJobs({ limit: 20 }),
    refetchInterval: 5000,
  });

  const voicesQuery = useQuery({
    queryKey: ["dub-provider-voices", targetLanguage],
    queryFn: () => getDubProviderVoices(false, targetLanguage),
    staleTime: 24 * 60 * 60 * 1000,
  });

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
        void queryClient.invalidateQueries({ queryKey: ["jobs", "running"] });
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
      if (
        !Number.isFinite(parsedOutputVideoSpeed) ||
        parsedOutputVideoSpeed <= 0 ||
        parsedOutputVideoSpeed > 4
      ) {
        throw new Error(
          "Output video speed must be greater than 0 and no more than 4.",
        );
      }

      const parsedOriginalAudioVolume = Number(originalAudioVolume);
      if (
        !Number.isFinite(parsedOriginalAudioVolume) ||
        parsedOriginalAudioVolume < 0 ||
        parsedOriginalAudioVolume > 1
      ) {
        throw new Error("Original audio volume must be between 0 and 1.");
      }

      const trimmedTranslationContext = translationContext.trim();
      if (trimmedTranslationContext.length > 100) {
        throw new Error("Translation context must be 100 characters or fewer.");
      }

      const collection = await createVideoCollection({
        source_language: sourceLanguage,
        target_language: targetLanguage,
        translation_context: trimmedTranslationContext || null,
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

  const selectedJob = jobQuery.data ?? null;
  const activeBackgroundJob = useMemo(() => {
    const activeJobs = activeJobsQuery.data?.items ?? [];
    return (
      activeJobs.find((item) => runningJobStatuses.has(item.status)) ?? null
    );
  }, [activeJobsQuery.data?.items]);
  const job =
    selectedJob && runningJobStatuses.has(selectedJob.status)
      ? selectedJob
      : activeBackgroundJob;
  const voices = voicesQuery.data?.items ?? [];
  const selectedVoice =
    voices.find((voice) => voice.voice_id === voiceId) ?? null;

  useEffect(() => {
    if (!activeBackgroundJob) return;
    if (
      selectedJobId === null ||
      (selectedJob && !runningJobStatuses.has(selectedJob.status))
    ) {
      setSelectedJobId(activeBackgroundJob.id);
    }
  }, [activeBackgroundJob, selectedJob, selectedJobId]);

  const dashboardError = jobQuery.error ?? activeJobsQuery.error;
  const error =
    formError ??
    (dashboardError
      ? getErrorMessage(dashboardError, "Unable to refresh the dashboard.")
      : null);

  useErrorToast(error, "Dashboard error");

  async function refreshDashboard(jobId = selectedJobId) {
    if (!jobId) return;

    setFormError(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
      queryClient.invalidateQueries({ queryKey: ["jobs", "running"] }),
    ]);
  }

  function handleCreateAndUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    createAndUploadMutation.mutate();
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
            Create a video collection, upload source video, and watch websocket
            status updates while the pipeline runs in the background.
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

      <section className="mb-6 grid gap-6 lg:grid-cols-[minmax(0,42rem)]">
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
                <div className="flex items-center justify-between gap-3">
                  <Label htmlFor="translation-context">
                    Translation context
                  </Label>
                  <span className="text-xs text-muted-foreground">
                    {translationContext.length}/100
                  </span>
                </div>
                <Input
                  id="translation-context"
                  maxLength={100}
                  placeholder="Optional: names, tone, topic"
                  value={translationContext}
                  onChange={(event) =>
                    setTranslationContext(event.target.value)
                  }
                />
                <p className="text-xs text-muted-foreground">
                  Added to the translation prompt to preserve wording, tone, and
                  names.
                </p>
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
                        {voice.credit_factor && voice.credit_factor > 1 ? (
                          <>
                            {voice.name}
                            <Badge variant="secondary">
                              x{voice.credit_factor}
                            </Badge>
                          </>
                        ) : (
                          voice.name
                        )}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedVoice && (
                  <div className="grid gap-2 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
                    <div className="flex flex-wrap gap-x-3 gap-y-1">
                      <span className="font-medium text-foreground">
                        {selectedVoice.name}
                      </span>
                      <span className="break-all">
                        Code: {selectedVoice.voice_id}
                      </span>
                      {selectedVoice.credit_factor &&
                      selectedVoice.credit_factor > 1 ? (
                        <span>
                          Credit factor: x{selectedVoice.credit_factor}
                        </span>
                      ) : null}
                    </div>
                    {selectedVoice.demo ? (
                      <audio
                        className="h-9 w-full"
                        controls
                        preload="none"
                        src={selectedVoice.demo}
                      >
                        <a
                          href={selectedVoice.demo}
                          target="_blank"
                          rel="noreferrer"
                        >
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
                    disabled={
                      voicesQuery.isFetching || refreshVoicesMutation.isPending
                    }
                    onClick={() => refreshVoicesMutation.mutate()}
                  >
                    {(voicesQuery.isFetching ||
                      refreshVoicesMutation.isPending) && (
                      <Loader2 className="animate-spin" />
                    )}
                    Refresh voices
                  </Button>
                </div>
              </div>
              <div className="grid gap-4 sm:grid-cols-2 items-start">
                <div className="grid gap-2">
                  <Label htmlFor="output-video-speed">Output video speed</Label>
                  <Input
                    id="output-video-speed"
                    type="number"
                    min="0.1"
                    max="4"
                    step="0.05"
                    value={outputVideoSpeed}
                    onChange={(event) =>
                      setOutputVideoSpeed(event.target.value)
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Applied only during final muxing; default is 1x.
                  </p>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="original-audio-volume">
                    Original audio volume
                  </Label>
                  <Input
                    id="original-audio-volume"
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    value={originalAudioVolume}
                    onChange={(event) =>
                      setOriginalAudioVolume(event.target.value)
                    }
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
      </section>

      {job && <JobStatusCard job={job} />}
    </>
  );
}
