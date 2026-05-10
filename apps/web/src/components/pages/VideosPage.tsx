import { useMemo, useState } from "react";
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import type { ProviderRequest, UploadPlatform, VideoSegment } from "../../interfaces/job";
import {
  deleteJob,
  deleteVideoCollection,
  getConnectedAccounts,
  getProviderRequests,
  getVideoCollectionSegments,
  getVideoCollections,
  publishJobUpload,
} from "../../services/api";

import { VideosDraft } from "./VideosDraft";

const VIDEO_COLLECTIONS_PAGE_SIZE = 10;

export default function VideosPage() {
  const [collectionsPage, setCollectionsPage] = useState(0);
  const queryClient = useQueryClient();

  const youtubeConnectedAccountsQuery = useQuery({
    queryKey: ["connected-accounts", "youtube", "videos"],
    queryFn: () => getConnectedAccounts("youtube"),
  });

  const collectionsQuery = useQuery({
    queryKey: ["video-collections", collectionsPage],
    queryFn: () =>
      getVideoCollections({
        limit: VIDEO_COLLECTIONS_PAGE_SIZE,
        offset: collectionsPage * VIDEO_COLLECTIONS_PAGE_SIZE,
      }),
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

  const segmentsByCollectionId = useMemo(() => {
    const segments = new Map<number, VideoSegment[]>();
    collections.forEach((collection, index) => {
      segments.set(collection.id, segmentQueries[index]?.data ?? []);
    });
    return segments;
  }, [collections, segmentQueries]);

  const allSegments = useMemo(
    () => Array.from(segmentsByCollectionId.values()).flat(),
    [segmentsByCollectionId],
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
      requestsByJobId.set(segment.job_id, providerRequestQueries[index]?.data ?? []);
    });
    return requestsByJobId;
  }, [allSegments, providerRequestQueries]);

  const publishMutation = useMutation({
    mutationFn: async ({
      jobIds,
      platform,
    }: {
      jobIds: number[];
      platform: UploadPlatform;
    }) => {
      const accountId =
        platform === "youtube"
          ? (youtubeConnectedAccounts[0]?.id ?? null)
          : null;

      return Promise.all(
        jobIds.map((jobId) =>
          publishJobUpload(jobId, {
            platform,
            connected_account_id: accountId,
            title: `Dubbed video job #${jobId}`,
            description: "Published from the AI Lab videos dashboard.",
            privacy: "public",
          }),
        ),
      );
    },
    onSuccess: async (results) => {
      await Promise.all(
        results.map((result) =>
          queryClient.invalidateQueries({
            queryKey: ["provider-requests", result.job_id],
          }),
        ),
      );
    },
  });

  const deleteCollectionMutation = useMutation({
    mutationFn: deleteVideoCollection,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["video-collections"] });
    },
  });

  const deleteJobMutation = useMutation({
    mutationFn: async ({ jobId }: { collectionId: number; jobId: number }) => {
      await deleteJob(jobId);
    },
    onSuccess: async (_, variables) => {
      queryClient.removeQueries({
        queryKey: ["provider-requests", variables.jobId],
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["video-collections"] }),
        queryClient.invalidateQueries({
          queryKey: ["video-collection-segments", variables.collectionId],
        }),
      ]);
    },
  });

  const isVideosLoading =
    collectionsQuery.isLoading ||
    segmentQueries.some((query) => query.isLoading) ||
    providerRequestQueries.some((query) => query.isLoading);
  const videosError =
    collectionsQuery.error ??
    segmentQueries.find((query) => query.error)?.error ??
    providerRequestQueries.find((query) => query.error)?.error ??
    youtubeConnectedAccountsQuery.error;

  return (
    <VideosDraft
      collections={collections}
      error={videosError}
      isLoading={isVideosLoading}
      onDeleteCollection={(collectionId) =>
        deleteCollectionMutation.mutate(collectionId)
      }
      onDeleteJob={(collectionId, jobId) =>
        deleteJobMutation.mutate({ collectionId, jobId })
      }
      onPageChange={setCollectionsPage}
      onPublish={(jobId, platform) =>
        publishMutation.mutate({ jobIds: [jobId], platform })
      }
      onPublishAll={(jobIds, platform) =>
        publishMutation.mutate({ jobIds, platform })
      }
      page={collectionsPage}
      pendingDeleteCollectionId={
        deleteCollectionMutation.isPending
          ? (deleteCollectionMutation.variables ?? null)
          : null
      }
      pendingDeleteJobId={
        deleteJobMutation.isPending
          ? (deleteJobMutation.variables?.jobId ?? null)
          : null
      }
      pageSize={VIDEO_COLLECTIONS_PAGE_SIZE}
      pendingPublish={
        publishMutation.isPending
          ? (publishMutation.variables ?? null)
          : null
      }
      providerRequestsByJobId={providerRequestsByJobId}
      publishError={publishMutation.error}
      deleteError={deleteCollectionMutation.error ?? deleteJobMutation.error}
      segmentsByCollectionId={segmentsByCollectionId}
      total={collectionsTotal}
      totalPages={collectionsTotalPages}
    />
  );
}
