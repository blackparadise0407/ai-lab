import { useMemo, useState } from "react";
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import type { ProviderRequest, UploadPlatform } from "../../interfaces/job";
import {
  getConnectedAccounts,
  getJobs,
  getProviderRequests,
  publishJobUpload,
} from "../../services/api";

import { VideosDraft } from "./VideosDraft";

const COMPLETED_JOBS_PAGE_SIZE = 10;

export default function VideosPage() {
  const [completedJobsPage, setCompletedJobsPage] = useState(0);
  const queryClient = useQueryClient();

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

  const quickPublishMutation = useMutation({
    mutationFn: async ({
      jobId,
      platform,
    }: {
      jobId: number;
      platform: UploadPlatform;
    }) => {
      const accountId =
        platform === "youtube"
          ? (youtubeConnectedAccounts[0]?.id ?? null)
          : null;

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

  const isVideosLoading =
    completedJobsQuery.isLoading ||
    completedJobProviderRequests.some((query) => query.isLoading);
  const videosError =
    completedJobsQuery.error ??
    completedJobProviderRequests.find((query) => query.error)?.error ??
    youtubeConnectedAccountsQuery.error;

  return (
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
          ? (quickPublishMutation.variables ?? null)
          : null
      }
      providerRequestsByJobId={completedProviderRequestsByJobId}
      publishError={quickPublishMutation.error}
      total={completedJobsTotal}
      totalPages={completedJobsTotalPages}
    />
  );
}
