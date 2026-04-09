import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, CalendarClock } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { formatUsd } from "@/lib/utils";
import type { BackfillCreateBody } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenantId: number;
}

/**
 * BackfillModal.
 *
 * Two-step flow in a single dialog:
 *   1. User picks start + end dates (default: 12 months ago → today).
 *      As they type, we debounce-call /api/tenants/{id}/backfills/preview
 *      and show batch count + estimated cost + list of batch dates.
 *   2. "Start backfill" hits POST /api/tenants/{id}/backfills, closes the
 *      modal, and navigates to /backfill/{jobId} where the progress page
 *      takes over.
 */
export function BackfillModal({ open, onOpenChange, tenantId }: Props) {
  // Default range: 12 months ago → today.
  const [startDate, setStartDate] = useState(() => monthsAgo(12));
  const [endDate, setEndDate] = useState(() => todayIso());
  const [label, setLabel] = useState("");

  const nav = useNavigate();
  const qc = useQueryClient();

  // Reset state on reopen so stale form values don't linger.
  useEffect(() => {
    if (open) {
      setStartDate(monthsAgo(12));
      setEndDate(todayIso());
      setLabel("");
    }
  }, [open]);

  const body = useMemo<BackfillCreateBody>(
    () => ({
      start_date: `${startDate}T00:00:00+00:00`,
      end_date: `${endDate}T23:59:59+00:00`,
      granularity: "monthly",
      label,
    }),
    [startDate, endDate, label]
  );

  const preview = useQuery({
    queryKey: ["backfill-preview", tenantId, body.start_date, body.end_date, body.label],
    queryFn: () => api.previewBackfill(tenantId, body),
    enabled: open && !!startDate && !!endDate,
    retry: false,
  });

  const start = useMutation({
    mutationFn: () => api.startBackfill(tenantId, body),
    onSuccess: (job) => {
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onOpenChange(false);
      nav(`/backfill/${job.id}`);
    },
  });

  const previewErr = preview.error as ApiError | null;
  const startErr = start.error as ApiError | null;
  const disabled =
    preview.isLoading ||
    !!previewErr ||
    !preview.data ||
    preview.data.batch_count === 0 ||
    start.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>
            <CalendarClock className="mr-2 inline-block h-5 w-5" />
            Historical backfill
          </DialogTitle>
          <DialogDescription>
            Populate this tenant with realistic demo data going back to a chosen
            start date. One run per month, executed serially. Manual and
            scheduled runs are blocked for this tenant until the backfill finishes.
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label className="text-xs">Start date</Label>
            <Input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              max={endDate}
            />
          </div>
          <div>
            <Label className="text-xs">End date</Label>
            <Input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              min={startDate}
              max={todayIso()}
            />
          </div>
        </div>

        <div>
          <Label className="text-xs">Label (optional)</Label>
          <Input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={preview.data?.label ?? "Backfill 2025-04 → 2026-04"}
          />
        </div>

        <div className="rounded-md border bg-muted/40 p-3 text-sm">
          {preview.isLoading && <p className="text-muted-foreground">Calculating plan…</p>}
          {previewErr && (
            <p className="flex items-start gap-2 text-destructive">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              {previewErr.message}
            </p>
          )}
          {preview.data && !previewErr && (
            <div className="space-y-1.5">
              <p>
                <strong>{preview.data.batch_count}</strong> monthly batch
                {preview.data.batch_count !== 1 ? "es" : ""}
                {preview.data.estimated_cost_usd != null && (
                  <>
                    {" "}· estimated total cost{" "}
                    <strong>{formatUsd(preview.data.estimated_cost_usd)}</strong>
                    <span className="text-xs text-muted-foreground">
                      {" "}(based on recent run average)
                    </span>
                  </>
                )}
                {preview.data.estimated_cost_usd == null && (
                  <span className="ml-1 text-xs text-muted-foreground">
                    (no cost history yet — first run establishes the baseline)
                  </span>
                )}
              </p>
              <div className="flex flex-wrap gap-1">
                {preview.data.batch_dates.map((iso) => (
                  <span
                    key={iso}
                    className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.65rem]"
                  >
                    {iso.slice(0, 7)}
                  </span>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                Each batch runs the full skill once, pretending its month is
                "today". Expect ~15 minutes per batch.
              </p>
            </div>
          )}
        </div>

        {startErr && (
          <p className="text-sm text-destructive">{startErr.message}</p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => start.mutate()} disabled={disabled}>
            {start.isPending ? "Starting…" : "Start backfill"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function monthsAgo(n: number): string {
  const d = new Date();
  d.setMonth(d.getMonth() - n);
  return d.toISOString().slice(0, 10);
}
