import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import { formatDateTime, formatUsd } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function RunHistoryPage() {
  const { data: runs, isLoading } = useQuery({
    queryKey: ["runs", "list"],
    queryFn: () => api.listRuns(100),
    refetchInterval: 5_000,
  });
  const { data: tenants } = useQuery({
    queryKey: ["tenants", "list"],
    queryFn: api.listTenants,
  });

  const tenantById = new Map((tenants ?? []).map((t) => [t.id, t]));

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild>
        <Link to="/">
          <ArrowLeft className="mr-1 h-4 w-4" />
          Back to dashboard
        </Link>
      </Button>

      <Card>
        <CardHeader>
          <CardTitle>Run history</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading && <p className="text-muted-foreground">Loading…</p>}
          {runs && runs.length === 0 && (
            <p className="text-muted-foreground">No runs yet.</p>
          )}
          {runs && runs.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 pr-4">#</th>
                  <th className="py-2 pr-4">Tenant</th>
                  <th className="py-2 pr-4">Trigger</th>
                  <th className="py-2 pr-4">Started</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Tool calls</th>
                  <th className="py-2 pr-4">Cost</th>
                  <th className="py-2 pr-4"></th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => {
                  const t = tenantById.get(run.tenant_id);
                  return (
                    <tr key={run.id} className="border-b last:border-0">
                      <td className="py-2 pr-4 font-mono text-xs">#{run.id}</td>
                      <td className="py-2 pr-4">
                        {t ? (
                          <span>
                            <strong>{t.name}</strong>
                            <span className="ml-2 rounded bg-muted px-1.5 py-0.5 font-mono text-[0.65rem]">
                              {t.environment}
                            </span>
                          </span>
                        ) : (
                          <span className="text-muted-foreground italic">(deleted tenant)</span>
                        )}
                      </td>
                      <td className="py-2 pr-4">
                        <Badge variant={run.trigger as "manual" | "schedule" | "backfill"}>
                          {run.trigger}
                        </Badge>
                        {run.parent_job_id != null && (
                          <div className="mt-0.5 text-[0.65rem] text-muted-foreground">
                            <Link
                              to={`/backfill/${run.parent_job_id}`}
                              className="hover:text-primary"
                            >
                              → backfill #{run.parent_job_id}
                            </Link>
                          </div>
                        )}
                        {run.backfill_date && (
                          <div className="mt-0.5 font-mono text-[0.65rem] text-cyan-400">
                            {run.backfill_date.slice(0, 10)}
                          </div>
                        )}
                      </td>
                      <td className="py-2 pr-4 text-muted-foreground">
                        {formatDateTime(run.started_at)}
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
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
