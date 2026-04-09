import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, CalendarClock, StopCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { BackfillJobDetail } from "@/lib/types";
import { formatDateTime, formatUsd } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function BackfillJobPage() {
  const { jobId } = useParams();
  const id = Number(jobId);
  const qc = useQueryClient();

  const jobQ = useQuery({
    queryKey: ["backfill", id],
    queryFn: () => api.getBackfill(id),
    // Poll while the job is running so the progress bar + child list
    // update without a page reload.
    refetchInterval: (q) => {
      const data = q.state.data as BackfillJobDetail | undefined;
      if (!data) return 2000;
      return data.status === "queued" || data.status === "running" ? 2000 : false;
    },
  });

  const cancel = useMutation({
    mutationFn: () => api.cancelBackfill(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["backfill", id] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  if (jobQ.isLoading) {
    return <p className="text-muted-foreground">Loading backfill…</p>;
  }
  if (!jobQ.data) {
    return <p className="text-destructive">Backfill not found.</p>;
  }
  const job = jobQ.data;
  const progress =
    job.total_batches > 0
      ? Math.round((job.completed_batches / job.total_batches) * 100)
      : 0;
  const canCancel = job.status === "queued" || job.status === "running";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/">
            <ArrowLeft className="mr-1 h-4 w-4" />
            Back to dashboard
          </Link>
        </Button>
        {canCancel && (
          <Button
            variant="destructive"
            size="sm"
            onClick={() => {
              if (
                confirm(
                  "Cancel this backfill? The current batch will finish, then the job stops."
                )
              ) {
                cancel.mutate();
              }
            }}
            disabled={cancel.isPending}
          >
            <StopCircle className="mr-1 h-4 w-4" />
            Cancel backfill
          </Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CalendarClock className="h-5 w-5" />
            {job.label}
            <Badge
              variant={
                job.status === "succeeded"
                  ? "succeeded"
                  : job.status === "running"
                  ? "running"
                  : job.status === "failed"
                  ? "failed"
                  : job.status === "cancelled"
                  ? "cancelled"
                  : "queued"
              }
            >
              {job.status}
            </Badge>
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            {formatDateTime(job.start_date)} → {formatDateTime(job.end_date)} ·{" "}
            {job.granularity} · triggered {formatDateTime(job.created_at)}
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="text-muted-foreground">
                {job.completed_batches} / {job.total_batches} batches complete
              </span>
              <span className="font-mono">{progress}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-[width] duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
          <div className="text-sm text-muted-foreground">
            Total cost so far: <strong>{formatUsd(job.total_cost_usd)}</strong>
          </div>
          {job.error_message && (
            <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
              <pre className="whitespace-pre-wrap break-words font-mono text-xs">
                {job.error_message}
              </pre>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Child runs</CardTitle>
        </CardHeader>
        <CardContent>
          {job.child_runs.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Waiting for the first batch to start…
            </p>
          )}
          {job.child_runs.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 pr-4">#</th>
                  <th className="py-2 pr-4">Batch date</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Tool calls</th>
                  <th className="py-2 pr-4">Cost</th>
                  <th className="py-2 pr-4"></th>
                </tr>
              </thead>
              <tbody>
                {job.child_runs.map((run) => (
                  <tr key={run.id} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-mono text-xs">#{run.id}</td>
                    <td className="py-2 pr-4 font-mono text-xs">
                      {run.backfill_date?.slice(0, 10) ?? "—"}
                    </td>
                    <td className="py-2 pr-4">
                      <Badge variant={run.status}>{run.status}</Badge>
                    </td>
                    <td className="py-2 pr-4">{run.tool_call_count}</td>
                    <td className="py-2 pr-4">{formatUsd(run.cost_usd)}</td>
                    <td className="py-2 pr-4">
                      <Button variant="outline" size="sm" asChild>
                        <Link to={`/runs/${run.id}`}>Open</Link>
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
