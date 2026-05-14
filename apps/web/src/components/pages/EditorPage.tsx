import { useMemo, useState } from "react";
import { Film, Loader2, Scissors, UploadCloud } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { UploadPlatform, VideoCollection, VideoCollectionRender, VideoSegment } from "../../interfaces/job";
import { formatDate, getErrorMessage } from "../../lib/format";
import { apiBaseUrl, createVideoCollectionRender, getConnectedAccounts, getVideoCollectionRenders, getVideoCollectionSegments, getVideoCollections, publishVideoCollectionRender } from "../../services/api";
import { uploadPlatformOptions } from "../../constants/uploadPlatforms";
import { EmptyState } from "../common/EmptyState";
import { PageHeader } from "../common/PageHeader";
import { Alert, AlertDescription, AlertTitle } from "../ui/alert";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";

const COLLECTIONS_PAGE_SIZE = 25;

export default function EditorPage() {
  const [selectedCollectionId, setSelectedCollectionId] = useState<number | null>(null);
  const [selectedSegmentIds, setSelectedSegmentIds] = useState<number[]>([]);
  const [platform, setPlatform] = useState<UploadPlatform>("youtube");
  const [title, setTitle] = useState("Combined AI Lab video");
  const [privacy, setPrivacy] = useState("private");
  const queryClient = useQueryClient();

  const collectionsQuery = useQuery({
    queryKey: ["video-collections", "editor"],
    queryFn: () => getVideoCollections({ limit: COLLECTIONS_PAGE_SIZE, offset: 0 }),
  });

  const collections = collectionsQuery.data?.items ?? [];
  const activeCollection = collections.find((collection) => collection.id === selectedCollectionId) ?? collections[0] ?? null;
  const collectionId = activeCollection?.id ?? null;

  const segmentsQuery = useQuery({
    queryKey: ["video-collection-segments", collectionId, "editor"],
    queryFn: () => getVideoCollectionSegments(collectionId!),
    enabled: collectionId !== null,
  });

  const rendersQuery = useQuery({
    queryKey: ["video-collection-renders", collectionId],
    queryFn: () => getVideoCollectionRenders(collectionId!),
    enabled: collectionId !== null,
  });

  const youtubeConnectedAccountsQuery = useQuery({
    queryKey: ["connected-accounts", "youtube", "editor"],
    queryFn: () => getConnectedAccounts("youtube"),
  });

  const segments = segmentsQuery.data ?? [];
  const completedSegments = useMemo(
    () => segments.filter((segment) => segment.job?.status === "completed" && segment.processed_artifact),
    [segments],
  );
  const effectiveSelectedSegmentIds = selectedSegmentIds.length > 0 ? selectedSegmentIds : completedSegments.map((segment) => segment.id);
  const renders = rendersQuery.data?.items ?? [];
  const latestCompletedRender = renders.find((render) => render.status === "completed" && render.output_path) ?? null;

  const renderMutation = useMutation({
    mutationFn: () => createVideoCollectionRender(collectionId!, { segment_ids: effectiveSelectedSegmentIds }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["video-collection-renders", collectionId] });
    },
  });

  const publishMutation = useMutation({
    mutationFn: (render: VideoCollectionRender) =>
      publishVideoCollectionRender(collectionId!, render.id, {
        platform,
        title,
        description: "Published from the AI Lab editor as one combined long video.",
        privacy,
        connected_account_id: platform === "youtube" ? (youtubeConnectedAccountsQuery.data?.[0]?.id ?? null) : null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["video-collection-renders", collectionId] });
    },
  });

  function handleCollectionChange(value: string) {
    setSelectedCollectionId(Number(value));
    setSelectedSegmentIds([]);
  }

  function toggleSegment(segmentId: number) {
    setSelectedSegmentIds((current) => {
      const base = current.length > 0 ? current : completedSegments.map((segment) => segment.id);
      return base.includes(segmentId) ? base.filter((id) => id !== segmentId) : [...base, segmentId];
    });
  }

  const pageError = collectionsQuery.error ?? segmentsQuery.error ?? rendersQuery.error ?? renderMutation.error ?? publishMutation.error;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Editor"
        title="Combine collection videos"
        description="Turn completed collection chunks into one long video, preview the render, and publish the combined upload instead of separate short segments."
      />

      {pageError ? (
        <Alert variant="destructive">
          <AlertTitle>Editor error</AlertTitle>
          <AlertDescription>{getErrorMessage(pageError, "Unable to load editor data.")}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(360px,0.75fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-2xl"><Scissors className="size-5" /> Collection timeline</CardTitle>
            <CardDescription>Select completed processed chunks to stitch in collection order.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-2">
              <Label>Video collection</Label>
              <Select value={String(collectionId ?? "")} onValueChange={handleCollectionChange}>
                <SelectTrigger>
                  <SelectValue placeholder="Choose a collection" />
                </SelectTrigger>
                <SelectContent>
                  {collections.map((collection) => (
                    <SelectItem key={collection.id} value={String(collection.id)}>
                      {collection.title || collection.original_filename || `Collection #${collection.id}`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {collectionsQuery.isLoading || segmentsQuery.isLoading ? (
              <EmptyState>Loading editor timeline…</EmptyState>
            ) : activeCollection ? (
              <div className="space-y-3">
                {segments.map((segment) => (
                  <SegmentRow
                    key={segment.id}
                    checked={effectiveSelectedSegmentIds.includes(segment.id)}
                    disabled={!(segment.job?.status === "completed" && segment.processed_artifact)}
                    segment={segment}
                    onToggle={() => toggleSegment(segment.id)}
                  />
                ))}
                {segments.length === 0 ? <EmptyState>This collection does not have segments yet.</EmptyState> : null}
              </div>
            ) : (
              <EmptyState>No video collections yet. Upload and process a collection before combining it.</EmptyState>
            )}

            <Button
              className="w-full rounded-2xl"
              disabled={!collectionId || effectiveSelectedSegmentIds.length === 0 || renderMutation.isPending}
              onClick={() => renderMutation.mutate()}
            >
              {renderMutation.isPending ? <Loader2 className="mr-2 size-4 animate-spin" /> : <Film className="mr-2 size-4" />}
              Combine selected videos
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-2xl"><UploadCloud className="size-5" /> Combined output</CardTitle>
            <CardDescription>Preview, download, or publish the newest long render.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {latestCompletedRender ? (
              <RenderCard
                collection={activeCollection!}
                render={latestCompletedRender}
                platform={platform}
                privacy={privacy}
                title={title}
                isPublishing={publishMutation.isPending}
                onPlatformChange={(value) => setPlatform(value as UploadPlatform)}
                onPrivacyChange={setPrivacy}
                onPublish={() => publishMutation.mutate(latestCompletedRender)}
                onTitleChange={setTitle}
              />
            ) : rendersQuery.isLoading ? (
              <EmptyState>Loading renders…</EmptyState>
            ) : (
              <EmptyState>No combined render yet. Select completed chunks and create one long video.</EmptyState>
            )}

            {renders.length > 0 ? (
              <div className="space-y-2">
                <p className="text-sm font-black uppercase tracking-[0.18em] text-muted-foreground">Render history</p>
                {renders.map((render) => (
                  <div key={render.id} className="rounded-2xl border bg-muted/30 p-3 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-bold">Render #{render.id}</span>
                      <Badge variant={render.status === "completed" ? "default" : "secondary"}>{render.status}</Badge>
                    </div>
                    <p className="mt-1 text-muted-foreground">{formatDate(render.created_at)} · {render.included_segment_ids.length} segments</p>
                    {render.error_message ? <p className="mt-1 text-destructive">{render.error_message}</p> : null}
                  </div>
                ))}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function SegmentRow({ checked, disabled, segment, onToggle }: { checked: boolean; disabled: boolean; segment: VideoSegment; onToggle: () => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-4 rounded-2xl border bg-card/70 p-4 shadow-sm has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={onToggle} className="size-5 accent-primary" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-bold">Chunk {segment.sequence_index}</p>
          <Badge variant={segment.job?.status === "completed" ? "default" : "secondary"}>{segment.job?.status ?? "unknown"}</Badge>
          {segment.processed_artifact ? <Badge variant="secondary">processed</Badge> : null}
        </div>
        <p className="mt-1 text-sm text-muted-foreground">{segment.start_seconds.toFixed(1)}s–{segment.end_seconds.toFixed(1)}s · {segment.duration_seconds.toFixed(1)}s</p>
      </div>
    </label>
  );
}

function RenderCard({ collection, render, platform, privacy, title, isPublishing, onPlatformChange, onPrivacyChange, onPublish, onTitleChange }: { collection: VideoCollection; render: VideoCollectionRender; platform: UploadPlatform; privacy: string; title: string; isPublishing: boolean; onPlatformChange: (value: string) => void; onPrivacyChange: (value: string) => void; onPublish: () => void; onTitleChange: (value: string) => void }) {
  const previewUrl = `${apiBaseUrl}/v1/video-collections/${collection.id}/renders/${render.id}/preview`;
  const downloadUrl = `${apiBaseUrl}/v1/video-collections/${collection.id}/renders/${render.id}/download`;

  return (
    <div className="space-y-4">
      <video className="aspect-video w-full rounded-2xl border bg-black" src={previewUrl} controls />
      <div className="grid gap-2 text-sm text-muted-foreground">
        <p><span className="font-bold text-foreground">Duration:</span> {render.duration_seconds?.toFixed(1) ?? "Unknown"}s</p>
        <p><span className="font-bold text-foreground">Segments:</span> {render.included_segment_ids.length}</p>
        {render.remote_url ? <a className="font-bold text-primary underline" href={render.remote_url}>Published video</a> : null}
      </div>
      <a className="inline-flex w-full items-center justify-center rounded-2xl bg-secondary px-4 py-2 text-sm font-semibold text-secondary-foreground shadow-xs hover:bg-secondary/80" href={downloadUrl}>Download combined video</a>
      <div className="space-y-3 rounded-2xl border bg-muted/30 p-4">
        <Label htmlFor="render-title">Publish title</Label>
        <Input id="render-title" value={title} onChange={(event) => onTitleChange(event.target.value)} />
        <Label>Platform</Label>
        <Select value={platform} onValueChange={onPlatformChange}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>{uploadPlatformOptions.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent>
        </Select>
        <Label>Privacy</Label>
        <Select value={privacy} onValueChange={onPrivacyChange}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="private">Private</SelectItem>
            <SelectItem value="unlisted">Unlisted</SelectItem>
            <SelectItem value="public">Public</SelectItem>
          </SelectContent>
        </Select>
        <Button className="w-full rounded-2xl" disabled={isPublishing || !title.trim()} onClick={onPublish}>
          {isPublishing ? <Loader2 className="mr-2 size-4 animate-spin" /> : <UploadCloud className="mr-2 size-4" />}
          Publish combined video
        </Button>
      </div>
    </div>
  );
}
