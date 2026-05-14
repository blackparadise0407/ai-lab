import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Controller, type SubmitHandler, useForm } from "react-hook-form";
import { Loader2, Plug, PlugZap } from "lucide-react";

import {
  DEFAULT_TARGET_LANGUAGE_CODE,
  targetLanguages,
} from "../../constants/languages";
import { getErrorMessage } from "../../lib/format";
import { useErrorToast } from "../../hooks/useErrorToast";
import type { JobEventPayload, JobListResponse } from "../../interfaces/job";
import {
  apiBaseUrl,
  createVideoCollection,
  getDubProviderVoices,
  getJob,
  getJobs,
  uploadVideoCollectionSource,
} from "../../services/api";
import {
  subscribeToJobEvents,
  subscribeToJobsEvents,
} from "../../services/jobEvents";
import {
  applyJobEventToRunningJobs,
  runningJobStatuses,
} from "../../services/runningJobs";
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

type CreateVideoCollectionFormValues = {
  sourceLanguage: string;
  targetLanguage: string;
  translationContext: string;
  voiceId: string;
  outputVideoSpeed: number;
  originalAudioVolume: number;
  splitThresholdSeconds: number;
  sourceVideo: FileList;
};

export default function DashboardPage() {
  const {
    control,
    formState: { errors },
    handleSubmit,
    register,
    setValue,
    watch,
  } = useForm<CreateVideoCollectionFormValues>({
    defaultValues: {
      sourceLanguage: "zh",
      targetLanguage: DEFAULT_TARGET_LANGUAGE_CODE,
      translationContext: "",
      voiceId: "",
      outputVideoSpeed: 1,
      originalAudioVolume: 0.15,
      splitThresholdSeconds: 60,
    },
  });
  const targetLanguage = watch("targetLanguage");
  const translationContext = watch("translationContext") ?? "";
  const voiceId = watch("voiceId") ?? "";
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
  });

  const voicesQuery = useQuery({
    queryKey: ["dub-provider-voices", targetLanguage],
    queryFn: () => getDubProviderVoices(false, targetLanguage),
    staleTime: 24 * 60 * 60 * 1000,
  });

  useEffect(() => {
    let wasDisconnected = false;

    return subscribeToJobsEvents({
      onOpen: () => {
        setSocketStatus("connected");
        if (wasDisconnected) {
          wasDisconnected = false;
          void queryClient.invalidateQueries({ queryKey: ["jobs", "running"] });
        }
      },
      onError: () => {
        wasDisconnected = true;
        setSocketStatus("error");
      },
      onClose: () => {
        wasDisconnected = true;
        setSocketStatus("disconnected");
      },
      onMessage: (payload: JobEventPayload) => {
        queryClient.setQueryData<JobListResponse | undefined>(
          ["jobs", "running"],
          (current) => applyJobEventToRunningJobs(current, payload),
        );
      },
    });
  }, [queryClient]);

  useEffect(() => {
    if (selectedJobId === null) {
      return undefined;
    }

    return subscribeToJobEvents(selectedJobId, {
      onMessage: (payload: JobEventPayload) => {
        if (payload.job) {
          queryClient.setQueryData(["job", selectedJobId], payload.job);
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
    mutationFn: async (values: CreateVideoCollectionFormValues) => {
      const file = values.sourceVideo?.[0] ?? null;
      if (!file) {
        throw new Error("Choose a source video before creating a collection.");
      }

      const parsedOutputVideoSpeed = Number(values.outputVideoSpeed);
      if (
        !Number.isFinite(parsedOutputVideoSpeed) ||
        parsedOutputVideoSpeed <= 0 ||
        parsedOutputVideoSpeed > 4
      ) {
        throw new Error(
          "Output video speed must be greater than 0 and no more than 4.",
        );
      }

      const parsedOriginalAudioVolume = Number(values.originalAudioVolume);
      if (
        !Number.isFinite(parsedOriginalAudioVolume) ||
        parsedOriginalAudioVolume < 0 ||
        parsedOriginalAudioVolume > 1
      ) {
        throw new Error("Original audio volume must be between 0 and 1.");
      }

      const trimmedTranslationContext = values.translationContext.trim();
      if (trimmedTranslationContext.length > 100) {
        throw new Error("Translation context must be 100 characters or fewer.");
      }

      const parsedSplitThresholdSeconds = Number(values.splitThresholdSeconds);
      if (
        !Number.isFinite(parsedSplitThresholdSeconds) ||
        parsedSplitThresholdSeconds <= 0
      ) {
        throw new Error("Split threshold must be greater than 0 seconds.");
      }

      const collection = await createVideoCollection({
        source_language: values.sourceLanguage,
        target_language: values.targetLanguage,
        translation_context: trimmedTranslationContext || null,
        title: file.name,
        voice_id: values.voiceId || null,
        output_video_speed: parsedOutputVideoSpeed,
        original_audio_volume: parsedOriginalAudioVolume,
        split_threshold_seconds: parsedSplitThresholdSeconds,
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
  const formValidationError = Object.values(errors).find(
    (fieldError) => typeof fieldError?.message === "string",
  )?.message as string | undefined;
  const error =
    formError ??
    formValidationError ??
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

  const handleCreateAndUpload: SubmitHandler<
    CreateVideoCollectionFormValues
  > = (values) => {
    setFormError(null);
    createAndUploadMutation.mutate(values);
  };

  return (
    <>
      <section className="relative mb-8 overflow-hidden rounded-[2rem] border bg-card/80 p-6 shadow-2xl shadow-slate-950/5 backdrop-blur sm:p-8 lg:p-10">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(34,211,238,0.16),transparent_32%)]" />
        <div className="relative grid gap-8 lg:grid-cols-[minmax(0,1fr)_24rem] lg:items-end">
          <div>
            <p className="text-sm font-black uppercase tracking-[0.24em] text-primary">
              AI-powered SaaS operations
            </p>
            <h1 className="mt-3 text-5xl font-black leading-none tracking-[-0.07em] text-slate-950 sm:text-7xl lg:text-8xl">
              AI Lab
            </h1>
            <p className="mt-6 max-w-3xl text-lg leading-8 text-muted-foreground">
              Create production-ready short video collections, monitor live AI
              dubbing pipelines, and move from source upload to publish with a
              clean enterprise workflow.
            </p>
            <div className="mt-6 flex flex-wrap gap-3 text-sm font-bold text-muted-foreground">
              <span className="rounded-full border bg-card/70 px-4 py-2 shadow-sm">Real-time jobs</span>
              <span className="rounded-full border bg-card/70 px-4 py-2 shadow-sm">AI dubbing</span>
              <span className="rounded-full border bg-card/70 px-4 py-2 shadow-sm">Multi-channel publishing</span>
            </div>
          </div>
          <Card className="border-primary/10 bg-slate-950 text-white shadow-2xl shadow-slate-950/20">
            <CardHeader>
              <CardDescription className="text-cyan-200">
                Connected API
              </CardDescription>
              <CardTitle className="break-all text-lg text-white">
                {apiBaseUrl}
              </CardTitle>
              <div className="mt-3 flex items-center gap-2 text-sm text-slate-300">
                {socketStatus === "connected" ? (
                  <PlugZap className="size-4 text-emerald-300" />
                ) : (
                  <Plug className="size-4" />
                )}
                <span>Websocket {socketStatus}</span>
              </div>
            </CardHeader>
          </Card>
        </div>
      </section>

      <section className="mb-6 grid gap-6 lg:grid-cols-[minmax(0,42rem)]">
        <Card>
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
            <form
              className="grid gap-4"
              onSubmit={handleSubmit(handleCreateAndUpload)}
            >
              <div className="grid gap-2">
                <Label htmlFor="source-language">Source language</Label>
                <Input
                  id="source-language"
                  {...register("sourceLanguage", {
                    required: "Source language is required.",
                  })}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="target-language">Target language</Label>
                <Controller
                  control={control}
                  name="targetLanguage"
                  rules={{ required: "Target language is required." }}
                  render={({ field }) => (
                    <Select
                      value={field.value}
                      onValueChange={(value) => {
                        field.onChange(value);
                        setValue("voiceId", "");
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
                  )}
                />
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
                  {...register("translationContext", {
                    maxLength: {
                      value: 100,
                      message:
                        "Translation context must be 100 characters or fewer.",
                    },
                  })}
                />
                <p className="text-xs text-muted-foreground">
                  Added to the translation prompt to preserve wording, tone, and
                  names.
                </p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="voice-id">Voice</Label>
                <Controller
                  control={control}
                  name="voiceId"
                  render={({ field }) => (
                    <Select
                      value={field.value || defaultVoiceValue}
                      disabled={voicesQuery.isLoading}
                      onValueChange={(value) =>
                        field.onChange(value === defaultVoiceValue ? "" : value)
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
                          <SelectItem
                            key={voice.voice_id}
                            value={voice.voice_id}
                          >
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
                  )}
                />
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
                    {...register("outputVideoSpeed", {
                      valueAsNumber: true,
                      min: {
                        value: 0.1,
                        message: "Output video speed must be greater than 0.",
                      },
                      max: {
                        value: 4,
                        message: "Output video speed must be no more than 4.",
                      },
                    })}
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
                    {...register("originalAudioVolume", {
                      valueAsNumber: true,
                      min: {
                        value: 0,
                        message: "Original audio volume must be at least 0.",
                      },
                      max: {
                        value: 1,
                        message:
                          "Original audio volume must be no more than 1.",
                      },
                    })}
                  />
                  <p className="text-xs text-muted-foreground">
                    Mixed under the dub at the final step; default is 0.15.
                  </p>
                </div>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="split-threshold-seconds">
                  Split threshold seconds
                </Label>
                <Input
                  id="split-threshold-seconds"
                  type="number"
                  min="1"
                  step="1"
                  {...register("splitThresholdSeconds", {
                    valueAsNumber: true,
                    min: {
                      value: 1,
                      message:
                        "Split threshold must be greater than 0 seconds.",
                    },
                  })}
                />
                <p className="text-xs text-muted-foreground">
                  Source videos longer than this are split into chunks; default
                  is 60 seconds.
                </p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="source-video">Source video</Label>
                <Input
                  id="source-video"
                  type="file"
                  accept="video/*"
                  {...register("sourceVideo", {
                    required:
                      "Choose a source video before creating a collection.",
                  })}
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
