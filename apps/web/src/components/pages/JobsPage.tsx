import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Loader2, Search, X } from "lucide-react";

import type { Job } from "../../interfaces/job";
import { formatDate, getErrorMessage } from "../../lib/format";
import { cn } from "../../lib/utils";
import { getJobs } from "../../services/api";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";

const JOBS_PAGE_SIZE = 20;
const ALL_STATUSES_VALUE = "__all_statuses__";

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

const statuses = Object.keys(statusLabels) as Job["status"][];

export default function JobsPage() {
  const [page, setPage] = useState(0);
  const [status, setStatus] = useState<Job["status"] | "">("");
  const [sourceLanguage, setSourceLanguage] = useState("");
  const [targetLanguage, setTargetLanguage] = useState("");
  const [currentStep, setCurrentStep] = useState("");

  const normalizedSourceLanguage = sourceLanguage.trim();
  const normalizedTargetLanguage = targetLanguage.trim();
  const normalizedCurrentStep = currentStep.trim();

  const jobsQuery = useQuery({
    queryKey: [
      "jobs",
      {
        page,
        status,
        sourceLanguage: normalizedSourceLanguage,
        targetLanguage: normalizedTargetLanguage,
        currentStep: normalizedCurrentStep,
      },
    ],
    queryFn: () =>
      getJobs({
        status: status || undefined,
        sourceLanguage: normalizedSourceLanguage || undefined,
        targetLanguage: normalizedTargetLanguage || undefined,
        currentStep: normalizedCurrentStep || undefined,
        limit: JOBS_PAGE_SIZE,
        offset: page * JOBS_PAGE_SIZE,
      }),
  });

  const response = jobsQuery.data ?? null;
  const jobs = response?.items ?? [];
  const total = response?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / JOBS_PAGE_SIZE));
  const canGoPrevious = page > 0;
  const canGoNext = page + 1 < totalPages;

  function resetPagination(action: () => void) {
    setPage(0);
    action();
  }

  function clearFilters() {
    setPage(0);
    setStatus("");
    setSourceLanguage("");
    setTargetLanguage("");
    setCurrentStep("");
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 lg:px-8">
      <PageHeader
        eyebrow="Job operations"
        title="Jobs"
        description="Browse dubbing jobs by newest created time, then narrow the list by status, language pair, or current pipeline step."
      />

      <Card className="mt-8 bg-card/90 shadow-xl shadow-slate-900/5">
        <CardHeader>
          <div>
            <CardDescription className="font-black uppercase tracking-[0.18em] text-primary">
              Filters
            </CardDescription>
            <CardTitle className="mt-2 text-2xl">Find jobs</CardTitle>
          </div>
          <CardAction>
            <Button type="button" variant="secondary" onClick={clearFilters}>
              <X />
              Clear
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div className="grid gap-2">
              <Label htmlFor="job-status-filter">Status</Label>
              <Select
                value={status || ALL_STATUSES_VALUE}
                onValueChange={(value) =>
                  resetPagination(() =>
                    setStatus(
                      value === ALL_STATUSES_VALUE
                        ? ""
                        : (value as Job["status"]),
                    ),
                  )
                }
              >
                <SelectTrigger id="job-status-filter">
                  <SelectValue placeholder="All statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_STATUSES_VALUE}>All statuses</SelectItem>
                  {statuses.map((statusValue) => (
                    <SelectItem key={statusValue} value={statusValue}>
                      {statusLabels[statusValue]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="source-language-filter">Source language</Label>
              <Input
                id="source-language-filter"
                placeholder="e.g. zh"
                value={sourceLanguage}
                onChange={(event) =>
                  resetPagination(() => setSourceLanguage(event.target.value))
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="target-language-filter">Target language</Label>
              <Input
                id="target-language-filter"
                placeholder="e.g. vi-VN"
                value={targetLanguage}
                onChange={(event) =>
                  resetPagination(() => setTargetLanguage(event.target.value))
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="current-step-filter">Current step</Label>
              <Input
                id="current-step-filter"
                placeholder="e.g. transcribing_source"
                value={currentStep}
                onChange={(event) =>
                  resetPagination(() => setCurrentStep(event.target.value))
                }
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="mt-6 bg-card/90 shadow-xl shadow-slate-900/5">
        <CardHeader>
          <div>
            <CardDescription className="font-black uppercase tracking-[0.18em] text-primary">
              Newest first
            </CardDescription>
            <CardTitle className="mt-2 text-2xl">Job list</CardTitle>
          </div>
          <CardAction>
            <Badge variant="secondary">{total} total</Badge>
          </CardAction>
        </CardHeader>
        <CardContent>
          {jobsQuery.isLoading ? (
            <EmptyState>
              <span className="inline-flex items-center gap-2">
                <Loader2 className="size-4 animate-spin" /> Loading jobs…
              </span>
            </EmptyState>
          ) : jobsQuery.error ? (
            <EmptyState>
              {getErrorMessage(jobsQuery.error, "Unable to load jobs.")}
            </EmptyState>
          ) : jobs.length === 0 ? (
            <EmptyState>No jobs match these filters.</EmptyState>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[56rem] text-left text-sm">
                <thead className="border-b text-xs uppercase tracking-[0.18em] text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Job</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Languages</th>
                    <th className="px-4 py-3">Current step</th>
                    <th className="px-4 py-3">Progress</th>
                    <th className="px-4 py-3">Created</th>
                    <th className="px-4 py-3">Updated</th>
                    <th className="px-4 py-3">Open</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {jobs.map((job) => (
                    <tr key={job.id} className="align-top hover:bg-muted/60">
                      <td className="px-4 py-4">
                        <div className="font-black text-foreground">#{job.id}</div>
                        <div className="mt-1 max-w-48 truncate text-xs text-muted-foreground">
                          {job.external_job_id}
                        </div>
                      </td>
                      <td className="px-4 py-4">
                        <StatusBadge status={job.status} />
                      </td>
                      <td className="px-4 py-4">
                        <Badge variant="secondary">
                          {job.source_language.toUpperCase()} →{" "}
                          {job.target_language.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="px-4 py-4 text-muted-foreground">
                        {job.current_step ?? "Waiting"}
                      </td>
                      <td className="px-4 py-4 font-bold">{job.progress_percent}%</td>
                      <td className="px-4 py-4 text-muted-foreground">
                        {formatDate(job.created_at)}
                      </td>
                      <td className="px-4 py-4 text-muted-foreground">
                        {formatDate(job.updated_at)}
                      </td>
                      <td className="px-4 py-4">
                        <Link
                          className={buttonVariants({
                            variant: "secondary",
                            size: "sm",
                          })}
                          to={`/jobs/${job.id}`}
                        >
                          <Search />
                          Details
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="mt-5 flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              Page <strong>{page + 1}</strong> of <strong>{totalPages}</strong>
            </p>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="secondary"
                disabled={!canGoPrevious}
                onClick={() => setPage((current) => Math.max(0, current - 1))}
              >
                <ArrowLeft />
                Previous
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={!canGoNext}
                onClick={() => setPage((current) => current + 1)}
              >
                Next
                <ArrowRight />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function StatusBadge({ status }: { status: Job["status"] }) {
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

  return (
    <Badge className={cn("uppercase", className)}>{statusLabels[status]}</Badge>
  );
}
