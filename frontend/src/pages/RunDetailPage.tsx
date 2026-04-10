import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Square } from "lucide-react";
import { api } from "@/lib/api";
import type { Run, RunEvent } from "@/lib/types";
import { formatDateTime, formatUsd, cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface SseDoneData {
  status: Run["status"];
  summary_md: string;
  error_message: string;
  tool_call_count: number;
  cost_usd: number | null;
  finished_at: string | null;
}

export function RunDetailPage() {
  const { runId: runIdParam } = useParams();
  const runId = Number(runIdParam);

  const [events, setEvents] = useState<RunEvent[]>([]);
  const [terminalState, setTerminalState] = useState<SseDoneData | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Initial run snapshot (one-shot) + historical events.
  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId),
  });
  const initialEvents = useQuery({
    queryKey: ["run", runId, "events"],
    queryFn: () => api.getRunEvents(runId, 0),
  });

  // Seed state once from the initial events query.
  useEffect(() => {
    if (initialEvents.data && events.length === 0) {
      setEvents(initialEvents.data);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialEvents.data]);

  // Open SSE if run is not yet terminal.
  useEffect(() => {
    if (!runQuery.data) return;
    if (["succeeded", "failed", "cancelled"].includes(runQuery.data.status)) return;

    const src = new EventSource(`/api/runs/${runId}/stream`);

    src.addEventListener("event", (raw) => {
      try {
        const ev = JSON.parse((raw as MessageEvent).data) as RunEvent;
        setEvents((prev) => [...prev, ev]);
      } catch (e) {
        console.warn("bad event", e);
      }
    });

    src.addEventListener("done", (raw) => {
      try {
        const d = JSON.parse((raw as MessageEvent).data) as SseDoneData;
        setTerminalState(d);
      } catch (e) {
        console.warn("bad done", e);
      }
      src.close();
    });

    src.addEventListener("error", () => {
      // Browser auto-reconnects; nothing to do.
    });

    return () => src.close();
  }, [runQuery.data, runId]);

  // Auto-scroll feed to bottom as events arrive.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events.length]);

  const run = runQuery.data;
  const status = terminalState?.status ?? run?.status ?? "queued";
  const summary = terminalState?.summary_md ?? run?.summary_md ?? "";
  const error = terminalState?.error_message ?? run?.error_message ?? "";
  const toolCalls = terminalState?.tool_call_count ?? run?.tool_call_count ?? 0;
  const cost = terminalState?.cost_usd ?? run?.cost_usd ?? null;

  const [stopping, setStopping] = useState(false);
  const isRunning = status === "queued" || status === "running";

  const handleStop = useCallback(async () => {
    if (!isRunning || stopping) return;
    setStopping(true);
    try {
      const updated = await api.cancelRun(runId);
      setTerminalState({
        status: updated.status as Run["status"],
        summary_md: updated.summary_md ?? "",
        error_message: updated.error_message ?? "",
        tool_call_count: updated.tool_call_count ?? 0,
        cost_usd: updated.cost_usd ?? null,
        finished_at: updated.finished_at ?? null,
      });
    } catch (e) {
      console.error("Failed to cancel run", e);
    } finally {
      setStopping(false);
    }
  }, [runId, isRunning, stopping]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/">
            <ArrowLeft className="mr-1 h-4 w-4" />
            Back to dashboard
          </Link>
        </Button>
        <Button variant="outline" size="sm" asChild>
          <Link to="/runs">History</Link>
        </Button>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              Run #{runId}
              <Badge variant={status}>{status}</Badge>
              {run && (
                <Badge variant={run.trigger as "manual" | "schedule" | "backfill"}>
                  {run.trigger}
                </Badge>
              )}
              {run?.backfill_date && (
                <span className="rounded bg-cyan-500/20 px-2 py-0.5 font-mono text-xs text-cyan-300">
                  {run.backfill_date.slice(0, 10)}
                </span>
              )}
            </CardTitle>
            {run && (
              <p className="mt-1 text-xs text-muted-foreground">
                started {formatDateTime(run.started_at)} · {toolCalls} tool calls · {events.length} events · {formatUsd(cost)}
                {run.parent_job_id != null && (
                  <>
                    {" "}·{" "}
                    <Link
                      to={`/backfill/${run.parent_job_id}`}
                      className="underline hover:text-primary"
                    >
                      parent backfill #{run.parent_job_id}
                    </Link>
                  </>
                )}
              </p>
            )}
          </div>
          {isRunning && (
            <Button
              variant="destructive"
              size="sm"
              onClick={handleStop}
              disabled={stopping}
            >
              <Square className="mr-1 h-4 w-4" />
              {stopping ? "Stopping…" : "Stop Run"}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          <div
            ref={scrollRef}
            className="max-h-[55vh] overflow-y-auto rounded border bg-muted/40 font-mono text-xs"
          >
            {events.length === 0 ? (
              <p className="p-4 text-muted-foreground">Waiting for first event…</p>
            ) : (
              events.map((ev) => <EventRow key={ev.seq} ev={ev} />)
            )}
          </div>
        </CardContent>
      </Card>

      {status === "succeeded" && summary && (
        <Card>
          <CardHeader>
            <CardTitle>Report</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap break-words text-sm">{summary}</pre>
          </CardContent>
        </Card>
      )}

      {status === "cancelled" && (
        <Card className="border-yellow-500/50">
          <CardHeader>
            <CardTitle className="text-yellow-400">Cancelled</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap break-words text-xs">{error || "Run was cancelled by user."}</pre>
          </CardContent>
        </Card>
      )}

      {status === "failed" && error && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap break-words text-xs">{error}</pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function EventRow({ ev }: { ev: RunEvent }) {
  const p = ev.payload as Record<string, unknown>;
  let body: React.ReactNode;

  if (ev.kind === "tool_use") {
    const input = (p.input as Record<string, unknown>) || {};
    const snippet = Object.entries(input)
      .slice(0, 3)
      .map(([k, v]) => {
        let s = typeof v === "string" ? v : JSON.stringify(v);
        if (s.length > 80) s = s.slice(0, 80) + "…";
        return `${k}=${s}`;
      })
      .join(", ");
    body = (
      <>
        <span className="text-blue-400">{String(p.tool ?? "?")}</span>
        {snippet && <span className="opacity-70"> ({snippet})</span>}
      </>
    );
  } else if (ev.kind === "text") {
    body = <span className="whitespace-pre-wrap">{String(p.text ?? "")}</span>;
  } else if (ev.kind === "result") {
    const cost = p.cost_usd != null ? ` · $${Number(p.cost_usd).toFixed(4)}` : "";
    body = (
      <em>
        result: {String(p.stop_reason ?? "?")}
        {cost}
      </em>
    );
  } else if (ev.kind === "error") {
    body = <strong>{String(p.error ?? "error")}</strong>;
  } else {
    body = <em>{JSON.stringify(p).slice(0, 200)}</em>;
  }

  const bgClass =
    ev.kind === "tool_use"
      ? "bg-blue-500/5"
      : ev.kind === "text"
      ? "bg-emerald-500/5"
      : ev.kind === "result"
      ? "bg-purple-500/5"
      : ev.kind === "error"
      ? "bg-red-500/10 text-red-300"
      : "";

  return (
    <div className={cn("border-b border-border/30 px-3 py-1.5 last:border-0", bgClass)}>
      <span className="mr-2 min-w-[80px] font-bold opacity-60">[{ev.kind}]</span>
      {body}
    </div>
  );
}
