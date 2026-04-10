import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { CalendarClock, CreditCard, MessageSquare, Play, Pencil, Plus, Settings, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { DashboardRow } from "@/lib/types";
import { formatDateTime, formatUsd } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BackfillModal } from "@/components/tenants/BackfillModal";

export function DashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.dashboard,
    // Poll while any tenant has a backfill running so the progress counter
    // and the "Run now" disabled state reflect reality without a refresh.
    refetchInterval: (q) => {
      const rows = (q.state.data as DashboardRow[] | undefined) ?? [];
      return rows.some((r) => r.in_flight_backfill) ? 5_000 : false;
    },
  });
  const qc = useQueryClient();
  const nav = useNavigate();
  const [backfillTenantId, setBackfillTenantId] = useState<number | null>(null);

  const startRun = useMutation({
    mutationFn: (tenantId: number) => api.startRun(tenantId),
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      nav(`/runs/${run.id}`);
    },
  });

  const deleteTenant = useMutation({
    mutationFn: (id: number) => api.deleteTenant(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dashboard"] }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">My tenants</h1>
          <p className="text-sm text-muted-foreground">
            Register a Zuora sandbox, configure its catalog, then kick off the nightly demo-data skill against it.
          </p>
        </div>
        <Button asChild>
          <Link to="/tenants/new">
            <Plus className="mr-1 h-4 w-4" />
            Add tenant
          </Link>
        </Button>
      </div>

      {isLoading && <p className="text-muted-foreground">Loading…</p>}

      {data && data.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            <p className="mb-4">No tenants yet. Add your first Zuora sandbox to get started.</p>
            <Button asChild>
              <Link to="/tenants/new">
                <Plus className="mr-1 h-4 w-4" />
                Add tenant
              </Link>
            </Button>
          </CardContent>
        </Card>
      )}

      {data && data.length > 0 && (
        <div className="space-y-3">
          {data.map((row: DashboardRow) => (
            <Card key={row.tenant.id}>
              <CardHeader className="flex flex-row items-center justify-between pb-3">
                <div className="space-y-0.5">
                  <CardTitle className="flex items-center gap-2">
                    {row.tenant.name}
                    <Badge
                      variant={
                        row.health === "ok"
                          ? "ok"
                          : row.health === "warn"
                          ? "warn"
                          : "error"
                      }
                    >
                      {row.health === "ok"
                        ? "✓ Configured"
                        : row.health === "warn"
                        ? `⚠ ${row.warnings.length} warning${row.warnings.length !== 1 ? "s" : ""}`
                        : `⛔ ${row.errors.length} error${row.errors.length !== 1 ? "s" : ""}`}
                    </Badge>
                  </CardTitle>
                  <p className="text-xs text-muted-foreground">
                    <span className="mr-2 rounded bg-muted px-1.5 py-0.5 font-mono text-[0.65rem] font-semibold">
                      {row.tenant.environment}
                    </span>
                    {row.tenant.base_url}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    onClick={() => startRun.mutate(row.tenant.id)}
                    disabled={
                      row.health === "error" ||
                      startRun.isPending ||
                      !!row.in_flight_backfill
                    }
                    title={
                      row.in_flight_backfill
                        ? `Blocked: backfill-${row.in_flight_backfill.id} is still running`
                        : row.health === "error"
                        ? row.errors.map((e) => e.message).join("\n")
                        : undefined
                    }
                  >
                    <Play className="mr-1 h-4 w-4" />
                    Run now
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => setBackfillTenantId(row.tenant.id)}
                    disabled={
                      row.health === "error" || !!row.in_flight_backfill
                    }
                    title={
                      row.in_flight_backfill
                        ? `Backfill-${row.in_flight_backfill.id} already running`
                        : row.health === "error"
                        ? "Fix config errors first"
                        : undefined
                    }
                  >
                    <CalendarClock className="mr-1 h-4 w-4" />
                    Backfill
                  </Button>
                  <Button variant="outline" asChild>
                    <Link to={`/tenants/${row.tenant.id}/chat`}>
                      <MessageSquare className="mr-1 h-4 w-4" />
                      Chat
                    </Link>
                  </Button>
                  <Button variant="outline" asChild>
                    <Link to={`/tenants/${row.tenant.id}/billing`}>
                      <CreditCard className="mr-1 h-4 w-4" />
                      Billing
                    </Link>
                  </Button>
                  <Button variant="outline" asChild>
                    <Link to={`/tenants/${row.tenant.id}/config`}>
                      <Settings className="mr-1 h-4 w-4" />
                      Configure
                    </Link>
                  </Button>
                  <Button variant="outline" asChild>
                    <Link to={`/tenants/${row.tenant.id}/edit`}>
                      <Pencil className="h-4 w-4" />
                    </Link>
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => {
                      if (confirm(`Delete tenant '${row.tenant.name}'? Stored credentials will be destroyed.`)) {
                        deleteTenant.mutate(row.tenant.id);
                      }
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {row.in_flight_backfill && (
                  <Link
                    to={`/backfill/${row.in_flight_backfill.id}`}
                    className="flex items-center justify-between rounded-md border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 transition-colors hover:bg-cyan-500/20"
                  >
                    <div className="flex items-center gap-2">
                      <CalendarClock className="h-4 w-4 text-cyan-400" />
                      <span className="font-semibold text-cyan-300">
                        Backfill running: {row.in_flight_backfill.label}
                      </span>
                    </div>
                    <span className="font-mono text-xs text-cyan-300">
                      {row.in_flight_backfill.completed_batches}/
                      {row.in_flight_backfill.total_batches} batches
                    </span>
                  </Link>
                )}
                <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Last run</p>
                  {row.last_run ? (
                    <Link
                      to={`/runs/${row.last_run.id}`}
                      className="mt-1 flex items-center gap-2 hover:text-primary"
                    >
                      <Badge variant={row.last_run.status as "succeeded" | "failed" | "running"}>
                        {row.last_run.status}
                      </Badge>
                      <span className="text-muted-foreground">
                        {formatDateTime(row.last_run.started_at)}
                        {row.last_run.cost_usd != null && ` · ${formatUsd(row.last_run.cost_usd)}`}
                      </span>
                    </Link>
                  ) : (
                    <p className="mt-1 text-muted-foreground">never run</p>
                  )}
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Next scheduled</p>
                  {row.next_sched ? (
                    <div className="mt-1">
                      <p>{formatDateTime(row.next_sched.next_run_at)}</p>
                      <p className="font-mono text-xs text-muted-foreground">
                        {row.next_sched.cron}
                        {row.next_sched.label && ` · ${row.next_sched.label}`}
                      </p>
                    </div>
                  ) : (
                    <p className="mt-1 text-muted-foreground">no schedule</p>
                  )}
                </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {backfillTenantId != null && (
        <BackfillModal
          open={backfillTenantId != null}
          onOpenChange={(open) => !open && setBackfillTenantId(null)}
          tenantId={backfillTenantId}
        />
      )}
    </div>
  );
}
