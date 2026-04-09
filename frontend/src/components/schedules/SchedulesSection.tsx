import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Schedule } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { CronBuilder } from "./CronBuilder";

export function SchedulesSection({ tenantId }: { tenantId: number }) {
  const qc = useQueryClient();
  const schedulesQ = useQuery({
    queryKey: ["schedules", tenantId],
    queryFn: () => api.listSchedules(tenantId),
  });

  const [draftCron, setDraftCron] = useState("7 9 * * *");
  const [draftLabel, setDraftLabel] = useState("");

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["schedules", tenantId] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const create = useMutation({
    mutationFn: () =>
      api.createSchedule(tenantId, { cron: draftCron, label: draftLabel, enabled: true }),
    onSuccess: () => {
      setDraftLabel("");
      invalidate();
    },
  });

  const toggle = useMutation({
    mutationFn: (sid: number) => api.toggleSchedule(tenantId, sid),
    onSuccess: invalidate,
  });

  const del = useMutation({
    mutationFn: (sid: number) => api.deleteSchedule(tenantId, sid),
    onSuccess: invalidate,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Schedules</CardTitle>
        <p className="text-xs text-muted-foreground">
          Automatic recurring runs. Uses server local time. Concurrent runs for
          the same tenant are prevented — overlapping fires are recorded as
          "skipped" in history.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {schedulesQ.isLoading && <p className="text-muted-foreground">Loading…</p>}

        {schedulesQ.data && schedulesQ.data.length === 0 && (
          <p className="text-sm text-muted-foreground">No schedules yet.</p>
        )}

        {schedulesQ.data && schedulesQ.data.length > 0 && (
          <div className="space-y-2">
            {schedulesQ.data.map((s) => (
              <ScheduleRow
                key={s.id}
                schedule={s}
                onToggle={() => toggle.mutate(s.id)}
                onDelete={() => {
                  if (confirm("Delete this schedule?")) {
                    del.mutate(s.id);
                  }
                }}
              />
            ))}
          </div>
        )}

        <Separator />

        <div className="space-y-3">
          <div>
            <h4 className="text-sm font-semibold">Add schedule</h4>
            <p className="text-xs text-muted-foreground">
              Pick a preset and dropdowns below, or switch to Custom for a raw cron expression.
            </p>
          </div>
          <CronBuilder value={draftCron} onChange={setDraftCron} />
          <div>
            <Label className="text-xs">Label (optional)</Label>
            <Input
              value={draftLabel}
              onChange={(e) => setDraftLabel(e.target.value)}
              placeholder="Nightly"
            />
          </div>
          <Button
            onClick={() => create.mutate()}
            disabled={create.isPending || !draftCron.trim()}
          >
            <Plus className="mr-1 h-4 w-4" />
            {create.isPending ? "Adding…" : "Add schedule"}
          </Button>
          {create.isError && (
            <p className="text-sm text-destructive">
              {(create.error as Error | null)?.message || "Failed to add schedule"}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function ScheduleRow({
  schedule,
  onToggle,
  onDelete,
}: {
  schedule: Schedule;
  onToggle: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-md border px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <Badge variant={schedule.enabled ? "ok" : "error"}>
            {schedule.enabled ? "● enabled" : "○ disabled"}
          </Badge>
          {schedule.label && <span className="text-sm font-medium">{schedule.label}</span>}
          <code className="truncate rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
            {schedule.cron}
          </code>
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          {schedule.enabled && schedule.next_run_at && (
            <span>next: {formatDateTime(schedule.next_run_at)}</span>
          )}
          {schedule.last_run_at && (
            <span className="ml-3">last: {formatDateTime(schedule.last_run_at)}</span>
          )}
        </div>
      </div>
      <div className="ml-3 flex items-center gap-1">
        <Button variant="outline" size="sm" onClick={onToggle}>
          {schedule.enabled ? "Disable" : "Enable"}
        </Button>
        <Button variant="ghost" size="icon" onClick={onDelete}>
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
