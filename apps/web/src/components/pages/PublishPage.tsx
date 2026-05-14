import { FormEvent, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { ExternalLink, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { uploadPlatformOptions } from "../../constants/uploadPlatforms";
import type {
  Job,
  ProviderRequest,
  PublishUploadResponse,
  UploadPlatform,
  VideoCollection,
  VideoCollectionDetail,
  VideoSegment,
} from "../../interfaces/job";
import { formatDate, getErrorMessage } from "../../lib/format";
import { useErrorToast } from "../../hooks/useErrorToast";
import { cn } from "../../lib/utils";
import {
  getConnectedAccounts,
  getJob,
  getProviderRequests,
  getVideoCollection,
  getVideoCollectionSegments,
  getVideoCollections,
  publishJobUpload,
} from "../../services/api";
import { EmptyState } from "../common/EmptyState";
import { PageHeader } from "../common/PageHeader";
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

const VIDEO_COLLECTIONS_PAGE_SIZE = 10;
const DEFAULT_TITLE_TEMPLATE = "{title} - Part {part}";

type CollectionRow = {
  collection: VideoCollection;
  segments: VideoSegment[];
};

type PublishTarget = {
  jobId: number;
  title: string;
};

type PublishVariables = {
  collectionId?: number;
  platform: UploadPlatform;
  connectedAccountId: number | null;
  description: string;
  privacy: string;
  targets: PublishTarget[];
};

type PublishSummary = {
  successes: PublishUploadResponse[];
  failures: { jobId: number; title: string; message: string }[];
};

function getPositiveIntegerParam(value: string | null) {
  if (!value) return null;

  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function getPlatformParam(value: string | null) {
  return uploadPlatformOptions.some((option) => option.value === value)
    ? (value as UploadPlatform)
    : "youtube";
}

export default function PublishPage() {
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const preselectedCollectionId = getPositiveIntegerParam(
    searchParams.get("collectionId"),
  );
  const preselectedJobId = getPositiveIntegerParam(searchParams.get("jobId"));

  const [collectionsPage, setCollectionsPage] = useState(0);
  const [platform, setPlatform] = useState<UploadPlatform>(() =>
    getPlatformParam(searchParams.get("platform")),
  );
  const [titleTemplate, setTitleTemplate] = useState(DEFAULT_TITLE_TEMPLATE);
  const [description, setDescription] = useState(
    "Published from the AI Lab publish workspace.",
  );
  const [privacy, setPrivacy] = useState("public");

  const youtubeConnectedAccountsQuery = useQuery({
    queryKey: ["connected-accounts", "youtube", "publish"],
    queryFn: () => getConnectedAccounts("youtube"),
  });

  const collectionsQuery = useQuery({
    queryKey: ["video-collections", "publish", collectionsPage],
    queryFn: () =>
      getVideoCollections({
        limit: VIDEO_COLLECTIONS_PAGE_SIZE,
        offset: collectionsPage * VIDEO_COLLECTIONS_PAGE_SIZE,
      }),
  });

  const selectedCollectionQuery = useQuery({
    queryKey: ["video-collection", preselectedCollectionId, "publish"],
    queryFn: () => getVideoCollection(preselectedCollectionId!),
    enabled: preselectedCollectionId !== null,
  });

  const directJobQuery = useQuery({
    queryKey: ["job", preselectedJobId, "publish"],
    queryFn: () => getJob(preselectedJobId!),
    enabled: preselectedJobId !== null,
  });

  const directJobProviderRequestsQuery = useQuery({
    queryKey: ["provider-requests", preselectedJobId, "publish"],
    queryFn: () => getProviderRequests(preselectedJobId!),
    enabled: preselectedJobId !== null,
  });

  const youtubeConnectedAccounts = youtubeConnectedAccountsQuery.data ?? [];
  const collectionsResponse = collectionsQuery.data ?? null;
  const collections = collectionsResponse?.items ?? [];
  const collectionsTotal = collectionsResponse?.total ?? 0;
  const collectionsTotalPages = Math.max(
    1,
    Math.ceil(collectionsTotal / VIDEO_COLLECTIONS_PAGE_SIZE),
  );

  const segmentQueries = useQueries({
    queries: collections.map((collection) => ({
      queryKey: ["video-collection-segments", collection.id],
      queryFn: () => getVideoCollectionSegments(collection.id),
      staleTime: 2_500,
    })),
  });

  const collectionRows = useMemo(() => {
    const rows = collections.map<CollectionRow>((collection, index) => ({
      collection,
      segments: segmentQueries[index]?.data ?? [],
    }));

    const selectedCollection = selectedCollectionQuery.data;
    if (!selectedCollection) return rows;

    const detailRow = collectionDetailToRow(selectedCollection);
    const existingIndex = rows.findIndex(
      (row) => row.collection.id === selectedCollection.id,
    );

    if (existingIndex === -1) {
      return [detailRow, ...rows];
    }

    return rows.map((row, index) =>
      index === existingIndex ? detailRow : row,
    );
  }, [collections, segmentQueries, selectedCollectionQuery.data]);

  const allSegments = useMemo(
    () => collectionRows.flatMap((row) => row.segments),
    [collectionRows],
  );

  const providerRequestQueries = useQueries({
    queries: allSegments.map((segment) => ({
      queryKey: ["provider-requests", segment.job_id],
      queryFn: () => getProviderRequests(segment.job_id),
      staleTime: 2_500,
    })),
  });

  const providerRequestsByJobId = useMemo(() => {
    const requestsByJobId = new Map<number, ProviderRequest[]>();
    allSegments.forEach((segment, index) => {
      requestsByJobId.set(
        segment.job_id,
        providerRequestQueries[index]?.data ?? [],
      );
    });
    return requestsByJobId;
  }, [allSegments, providerRequestQueries]);

  const connectedAccountId =
    platform === "youtube" ? (youtubeConnectedAccounts[0]?.id ?? null) : null;

  const publishMutation = useMutation({
    mutationFn: async (variables: PublishVariables) => {
      if (variables.targets.length === 0) {
        throw new Error("Choose at least one completed video to publish.");
      }

      const results = await Promise.allSettled(
        variables.targets.map((target) =>
          publishJobUpload(target.jobId, {
            platform: variables.platform,
            connected_account_id: variables.connectedAccountId,
            title: target.title,
            description: variables.description,
            privacy: variables.privacy,
          }),
        ),
      );

      return results.reduce<PublishSummary>(
        (summary, result, index) => {
          const target = variables.targets[index];
          if (result.status === "fulfilled") {
            summary.successes.push(result.value);
          } else {
            summary.failures.push({
              jobId: target.jobId,
              title: target.title,
              message: getErrorMessage(
                result.reason,
                "Unable to publish video.",
              ),
            });
          }
          return summary;
        },
        { successes: [], failures: [] },
      );
    },
    onSuccess: async (summary, variables) => {
      showPublishSummaryToast(summary, variables.platform);
      await Promise.all([
        ...summary.successes.map((result) =>
          queryClient.invalidateQueries({
            queryKey: ["provider-requests", result.job_id],
          }),
        ),
        ...(variables.collectionId
          ? [
              queryClient.invalidateQueries({
                queryKey: ["video-collection-segments", variables.collectionId],
              }),
            ]
          : []),
      ]);
    },
  });

  const isLoading =
    collectionsQuery.isLoading ||
    segmentQueries.some((query) => query.isLoading) ||
    providerRequestQueries.some((query) => query.isLoading) ||
    selectedCollectionQuery.isLoading ||
    directJobQuery.isLoading ||
    directJobProviderRequestsQuery.isLoading;
  const pageError =
    collectionsQuery.error ??
    selectedCollectionQuery.error ??
    directJobQuery.error ??
    segmentQueries.find((query) => query.error)?.error ??
    providerRequestQueries.find((query) => query.error)?.error ??
    directJobProviderRequestsQuery.error ??
    youtubeConnectedAccountsQuery.error;
  const directJob = directJobQuery.data ?? null;
  const directJobAlreadyShown = allSegments.some(
    (segment) => segment.job_id === preselectedJobId,
  );

  useErrorToast(
    pageError ? getErrorMessage(pageError, "Unable to load publish data.") : null,
    "Publish page error",
  );
  useErrorToast(
    publishMutation.error
      ? getErrorMessage(publishMutation.error, "Unable to publish videos.")
      : null,
    "Publish error",
  );

  function createTargets(row: CollectionRow, segments: VideoSegment[]) {
    return segments.map((segment) => ({
      jobId: segment.job_id,
      title: buildPublishTitle(titleTemplate, row.collection, segment),
    }));
  }

  function handlePublishCollection(row: CollectionRow) {
    const completedSegments = row.segments.filter(
      (segment) => segment.job?.status === "completed",
    );
    publishMutation.mutate({
      collectionId: row.collection.id,
      platform,
      connectedAccountId,
      description: description.trim(),
      privacy: privacy.trim() || "public",
      targets: createTargets(row, completedSegments),
    });
  }

  function handlePublishSegment(row: CollectionRow, segment: VideoSegment) {
    publishMutation.mutate({
      collectionId: row.collection.id,
      platform,
      connectedAccountId,
      description: description.trim(),
      privacy: privacy.trim() || "public",
      targets: createTargets(row, [segment]),
    });
  }

  function handlePublishDirectJob(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!directJob) return;

    publishMutation.mutate({
      platform,
      connectedAccountId,
      description: description.trim(),
      privacy: privacy.trim() || "public",
      targets: [
        {
          jobId: directJob.id,
          title: directJobTitle(titleTemplate, directJob),
        },
      ],
    });
  }

  function isPublishingJob(jobId: number) {
    return Boolean(
      publishMutation.isPending &&
      publishMutation.variables?.platform === platform &&
      publishMutation.variables.targets.some(
        (target) => target.jobId === jobId,
      ),
    );
  }

  return (
    <section className="grid gap-6">
      <PageHeader
        eyebrow="Publish"
        title="Publish collection videos"
        description="Publish completed videos from source collections. Long uploads stay grouped as collections while each completed segment is uploaded as its own platform video."
      />

      <Card className="bg-card/90 shadow-xl shadow-slate-900/5">
        <CardHeader>
          <div>
            <CardDescription className="font-black uppercase tracking-[0.18em] text-primary">
              Publish settings
            </CardDescription>
            <CardTitle className="mt-2 text-2xl">
              Platform and video metadata
            </CardTitle>
            <CardDescription>
              Use one metadata set for the collection, with a title template so
              each segment gets a clear title.
            </CardDescription>
          </div>
          <CardAction>
            {platform === "youtube" && youtubeConnectedAccounts.length === 0 ? (
              <Link
                className={buttonVariants({ variant: "secondary", size: "sm" })}
                to="/connector"
              >
                Connect YouTube
              </Link>
            ) : (
              <Badge variant="secondary">
                {platform === "youtube"
                  ? youtubeConnectedAccounts[0]?.display_name
                  : "Adapter credentials"}
              </Badge>
            )}
          </CardAction>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-3 md:grid-cols-3">
            {uploadPlatformOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                className={cn(
                  "rounded-2xl border bg-muted/60 p-4 text-left transition hover:border-primary/40 hover:bg-primary/5",
                  platform === option.value &&
                    "border-primary bg-primary/10 ring-2 ring-primary/20",
                )}
                onClick={() => setPlatform(option.value)}
              >
                <span className="font-black">{option.label}</span>
                <span className="mt-1 block text-sm text-muted-foreground">
                  {option.description}
                </span>
              </button>
            ))}
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_12rem] items-start">
            <div className="grid gap-2">
              <Label htmlFor="title-template">Title template</Label>
              <Input
                id="title-template"
                maxLength={150}
                placeholder="{title} - Part {part}"
                value={titleTemplate}
                onChange={(event) => setTitleTemplate(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Supports {"{title}"}, {"{part}"}, and {"{jobId}"} tokens.
              </p>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="publish-privacy">Privacy</Label>
              <Input
                id="publish-privacy"
                placeholder="public"
                value={privacy}
                onChange={(event) => setPrivacy(event.target.value)}
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
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      {directJob && !directJobAlreadyShown && (
        <DirectJobCard
          job={directJob}
          isPending={isPublishingJob(directJob.id)}
          onSubmit={handlePublishDirectJob}
          providerRequests={directJobProviderRequestsQuery.data ?? []}
          platform={platform}
          title={directJobTitle(titleTemplate, directJob)}
        />
      )}

      <Card className="bg-card/90 shadow-xl shadow-slate-900/5">
        <CardHeader>
          <div>
            <CardDescription className="font-black uppercase tracking-[0.18em] text-primary">
              Collections
            </CardDescription>
            <CardTitle className="mt-2 text-2xl">
              Publish completed collection videos
            </CardTitle>
            <CardDescription>
              Publish every completed segment in a collection or upload one
              segment at a time.
            </CardDescription>
          </div>
          <CardAction>
            <Badge variant="secondary">{collectionsTotal} total</Badge>
          </CardAction>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <EmptyState>Loading publishable collection videos…</EmptyState>
          ) : collectionRows.length > 0 ? (
            <div className="grid gap-4">
              {collectionRows.map((row) => (
                <CollectionPublishCard
                  key={row.collection.id}
                  isSelected={row.collection.id === preselectedCollectionId}
                  onPublishCollection={() => handlePublishCollection(row)}
                  onPublishSegment={(segment) =>
                    handlePublishSegment(row, segment)
                  }
                  pendingJobIds={
                    publishMutation.isPending
                      ? publishMutation.variables?.targets.map(
                          (target) => target.jobId,
                        )
                      : undefined
                  }
                  platform={platform}
                  providerRequestsByJobId={providerRequestsByJobId}
                  row={row}
                />
              ))}
            </div>
          ) : (
            <EmptyState>
              No video collections yet. Create a collection from the dashboard,
              then return here to publish completed videos.
            </EmptyState>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3 rounded-2xl border bg-card/80 p-4 text-sm text-muted-foreground shadow-xl shadow-slate-900/5 sm:flex-row sm:items-center sm:justify-between">
        <span>
          Showing{" "}
          {collections.length === 0
            ? 0
            : collectionsPage * VIDEO_COLLECTIONS_PAGE_SIZE + 1}
          –
          {Math.min(
            (collectionsPage + 1) * VIDEO_COLLECTIONS_PAGE_SIZE,
            collectionsTotal,
          )}{" "}
          of {collectionsTotal} collections
        </span>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={collectionsPage === 0 || isLoading}
            onClick={() => setCollectionsPage(Math.max(0, collectionsPage - 1))}
          >
            Previous
          </Button>
          <Badge variant="secondary">
            Page {collectionsPage + 1} of {collectionsTotalPages}
          </Badge>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={collectionsPage + 1 >= collectionsTotalPages || isLoading}
            onClick={() =>
              setCollectionsPage(
                Math.min(collectionsTotalPages - 1, collectionsPage + 1),
              )
            }
          >
            Next
          </Button>
        </div>
      </div>
    </section>
  );
}

function collectionDetailToRow(
  collection: VideoCollectionDetail,
): CollectionRow {
  return {
    collection,
    segments: collection.segments,
  };
}

function buildPublishTitle(
  template: string,
  collection: VideoCollection,
  segment: VideoSegment,
) {
  const fallbackTitle =
    collection.title ||
    collection.original_filename ||
    `Collection #${collection.id}`;
  const baseTemplate = template.trim() || DEFAULT_TITLE_TEMPLATE;
  return applyTitleTemplate(baseTemplate, {
    title: fallbackTitle,
    part: String(segment.sequence_index),
    jobId: String(segment.job_id),
  }).slice(0, 150);
}

function directJobTitle(template: string, job: Job) {
  const baseTemplate = template.trim() || "Dubbed video job #{jobId}";
  return applyTitleTemplate(baseTemplate, {
    title: `Dubbed video job #${job.id}`,
    part: "1",
    jobId: String(job.id),
  }).slice(0, 150);
}

function applyTitleTemplate(
  template: string,
  tokens: { title: string; part: string; jobId: string },
) {
  return template
    .split("{title}")
    .join(tokens.title)
    .split("{part}")
    .join(tokens.part)
    .split("{jobId}")
    .join(tokens.jobId);
}

function CollectionPublishCard({
  isSelected,
  onPublishCollection,
  onPublishSegment,
  pendingJobIds,
  platform,
  providerRequestsByJobId,
  row,
}: {
  isSelected: boolean;
  onPublishCollection: () => void;
  onPublishSegment: (segment: VideoSegment) => void;
  pendingJobIds?: number[];
  platform: UploadPlatform;
  providerRequestsByJobId: Map<number, ProviderRequest[]>;
  row: CollectionRow;
}) {
  const completedSegments = row.segments.filter(
    (segment) => segment.job?.status === "completed",
  );
  const isCollectionPending = completedSegments.some((segment) =>
    pendingJobIds?.includes(segment.job_id),
  );

  return (
    <article
      className={cn(
        "rounded-2xl border bg-card p-4",
        isSelected && "border-primary ring-2 ring-primary/20",
      )}
    >
      <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr_auto] lg:items-start">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-black">
              {row.collection.title ||
                row.collection.original_filename ||
                `Collection #${row.collection.id}`}
            </h3>
            <StatusBadge status={row.collection.status} />
            {isSelected && <Badge>Selected</Badge>}
          </div>
          <div className="mt-1 break-all text-sm text-muted-foreground">
            {row.collection.external_collection_id}
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-sm">
            <Badge variant="secondary">
              {row.collection.source_language.toUpperCase()} →{" "}
              {row.collection.target_language.toUpperCase()}
            </Badge>
            <Badge variant="secondary">
              {row.collection.completed_segment_count}/
              {row.collection.segment_count} complete
            </Badge>
            {row.collection.total_duration_seconds !== null &&
              row.collection.total_duration_seconds !== undefined && (
                <Badge variant="secondary">
                  {formatDuration(row.collection.total_duration_seconds)} total
                </Badge>
              )}
          </div>
        </div>

        <div className="grid gap-2">
          <div className="flex items-center justify-between text-sm font-bold">
            <span>Collection progress</span>
            <span>{row.collection.progress_percent}%</span>
          </div>
          <Progress value={row.collection.progress_percent} />
          <div className="text-sm text-muted-foreground">
            Updated {formatDate(row.collection.updated_at)}
          </div>
        </div>

        <Button
          type="button"
          size="sm"
          disabled={completedSegments.length === 0 || isCollectionPending}
          onClick={onPublishCollection}
        >
          {isCollectionPending && <Loader2 className="animate-spin" />}
          Publish {completedSegments.length} to {platformLabel(platform)}
        </Button>
      </div>

      <div className="mt-4 overflow-x-auto rounded-2xl border">
        <table className="w-full min-w-[58rem] text-left text-sm">
          <thead className="bg-muted/60 text-xs font-black uppercase tracking-[0.16em] text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Part</th>
              <th className="px-4 py-3">Time range</th>
              <th className="px-4 py-3">Job</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Publish status</th>
              <th className="px-4 py-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y bg-card">
            {row.segments.length > 0 ? (
              row.segments.map((segment) => {
                const isPending =
                  pendingJobIds?.includes(segment.job_id) ?? false;
                const publishStatus = getPublishStatus(
                  providerRequestsByJobId.get(segment.job_id) ?? [],
                  platform,
                );

                return (
                  <tr key={segment.id}>
                    <td className="px-4 py-4 align-top font-black">
                      Part {segment.sequence_index}
                    </td>
                    <td className="px-4 py-4 align-top text-muted-foreground">
                      {formatDuration(segment.start_seconds)}–
                      {formatDuration(segment.end_seconds)}
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
                      <PlatformPublishBadge
                        platform={platform}
                        status={publishStatus}
                      />
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="flex justify-end">
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          disabled={
                            isPending || segment.job?.status !== "completed"
                          }
                          onClick={() => onPublishSegment(segment)}
                        >
                          {isPending && <Loader2 className="animate-spin" />}
                          Publish
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td
                  className="px-4 py-6 text-center text-muted-foreground"
                  colSpan={6}
                >
                  No chunks have been created for this collection yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function DirectJobCard({
  isPending,
  job,
  onSubmit,
  providerRequests,
  platform,
  title,
}: {
  isPending: boolean;
  job: Job;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  providerRequests: ProviderRequest[];
  platform: UploadPlatform;
  title: string;
}) {
  return (
    <Card className="bg-card/90 shadow-xl shadow-slate-900/5">
      <CardHeader>
        <div>
          <CardDescription className="font-black uppercase tracking-[0.18em] text-primary">
            Direct job
          </CardDescription>
          <CardTitle className="mt-2 text-2xl">Job #{job.id}</CardTitle>
          <CardDescription>
            This job was opened from a direct link. Publish it here even if its
            source collection is not visible on the current page.
          </CardDescription>
        </div>
        <CardAction>
          <StatusBadge status={job.status} />
        </CardAction>
      </CardHeader>
      <CardContent>
        <form className="grid gap-4" onSubmit={onSubmit}>
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">Title: {title}</Badge>
            <PlatformPublishBadge
              platform={platform}
              status={getPublishStatus(providerRequests, platform)}
            />
          </div>
          <Button
            type="submit"
            disabled={isPending || job.status !== "completed"}
          >
            {isPending && <Loader2 className="animate-spin" />}
            Publish direct job to {platformLabel(platform)}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function showPublishSummaryToast(
  summary: PublishSummary,
  platform: UploadPlatform,
) {
  const hasFailures = summary.failures.length > 0;
  const title = hasFailures
    ? "Publish completed with errors"
    : "Publish completed";
  const description = (
    <PublishSummaryToastDescription platform={platform} summary={summary} />
  );

  if (hasFailures) {
    toast.error(title, { description });
    return;
  }

  toast.success(title, { description });
}

function PublishSummaryToastDescription({
  platform,
  summary,
}: {
  platform: UploadPlatform;
  summary: PublishSummary;
}) {
  const hasFailures = summary.failures.length > 0;

  return (
    <div className="grid gap-2">
      <p>
        {summary.successes.length} video(s) published to {" "}
        {platformLabel(platform)}.
        {hasFailures && ` ${summary.failures.length} video(s) failed.`}
      </p>
      {summary.successes.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {summary.successes.map((result) => (
            <PublishedResultLink result={result} key={result.job_id} />
          ))}
        </div>
      )}
      {hasFailures && (
        <ul className="list-disc pl-5">
          {summary.failures.map((failure) => (
            <li key={failure.jobId}>
              Job #{failure.jobId}: {failure.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PublishedResultLink({ result }: { result: PublishUploadResponse }) {
  if (!result.remote_url) {
    return (
      <Badge className="bg-emerald-100 text-emerald-700">
        Job #{result.job_id}
      </Badge>
    );
  }

  return (
    <a
      className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-3 py-1 text-xs font-bold text-emerald-700 underline-offset-2 hover:underline"
      href={result.remote_url}
      target="_blank"
      rel="noreferrer"
    >
      Job #{result.job_id}
      <ExternalLink className="size-3" />
    </a>
  );
}

function getPublishStatus(
  providerRequests: ProviderRequest[],
  platform: UploadPlatform,
) {
  return providerRequests.find(
    (request) => request.provider_name === `upload_${platform}`,
  )?.status;
}

function PlatformPublishBadge({
  platform,
  status,
}: {
  platform: UploadPlatform;
  status?: ProviderRequest["status"];
}) {
  if (!status) {
    return (
      <Badge variant="secondary">
        {platformLabel(platform)}: not published
      </Badge>
    );
  }

  return (
    <Badge className="bg-emerald-100 text-emerald-700">
      {platformLabel(platform)}: {status}
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

  return (
    <Badge className={className} variant={className ? undefined : "secondary"}>
      {status}
    </Badge>
  );
}

function platformLabel(platform: UploadPlatform) {
  return (
    uploadPlatformOptions.find((option) => option.value === platform)?.label ??
    platform
  );
}

function formatDuration(totalSeconds: number) {
  const safeSeconds = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(safeSeconds / 60);
  const seconds = safeSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}
