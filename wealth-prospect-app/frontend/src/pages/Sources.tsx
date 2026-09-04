import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import { Badge, Card, ErrorBox, Spinner } from "@/components/ui";

const CAT: Record<string, string> = { property: "Property", equity: "Public equity", business: "Business", giving: "Giving", income: "Income", demographic: "Demographic", life: "Life events" };

export default function Sources() {
  const q = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  if (q.isLoading) return <Spinner />;
  if (q.error || !q.data) return <ErrorBox error={q.error} />;
  return (
    <div className="max-w-6xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Data sources</h1>
        <p className="text-sm text-slate-500 mt-1 max-w-3xl">
          Every fact in Prospect Lens traces back to one of these sources, with its legal basis and cost shown here. The strategy is public-record-first:
          SEC, FEC, IRS and county data are free, legally clean for marketing use, and — unlike purchased consumer data — explainable to the prospect if they ask.
        </p>
        <div className={clsx("mt-3 inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium", q.data.live_connectors ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800")}>
          <span className={clsx("h-2 w-2 rounded-full", q.data.live_connectors ? "bg-emerald-500" : "bg-amber-500")} />
          {q.data.live_connectors ? "Live connectors enabled" : "Synthetic mode — set LIVE_CONNECTORS=true to call real APIs"}
        </div>
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        {q.data.sources.map((s) => (
          <Card key={s.key}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2"><h3 className="font-semibold">{s.name}</h3><Badge className="bg-slate-50 text-slate-600 ring-slate-200">{CAT[s.category] ?? s.category}</Badge></div>
                <p className="text-sm text-slate-600 mt-1">{s.description}</p>
              </div>
              <Badge className={s.mode === "live" ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : s.supports_live ? "bg-sky-50 text-sky-800 ring-sky-200" : "bg-slate-50 text-slate-600 ring-slate-200"}>
                {s.mode === "live" ? "live" : s.supports_live ? "live-ready" : "synthetic"}
              </Badge>
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 mt-4 text-xs">
              <div className="col-span-2"><dt className="kicker">Legal basis</dt><dd className="text-slate-700 mt-0.5">{s.legal_basis}</dd></div>
              <div><dt className="kicker">Cost</dt><dd className="text-slate-700 mt-0.5">{s.cost}</dd></div>
              <div><dt className="kicker">Coverage</dt><dd className="text-slate-700 mt-0.5">{s.coverage}</dd></div>
              <div><dt className="kicker">Refresh</dt><dd className="text-slate-700 mt-0.5">{s.refresh}</dd></div>
              <div><dt className="kicker">Signals stored</dt><dd className="text-slate-700 mt-0.5 tabular-nums">{s.signal_count.toLocaleString()} · latest {relTime(s.last_observed)}</dd></div>
              <div className="col-span-2"><dt className="kicker">Produces</dt><dd className="flex flex-wrap gap-1 mt-1">{s.signal_labels.map((l) => <Badge key={l} className="bg-white text-slate-600 ring-slate-200">{l}</Badge>)}</dd></div>
            </dl>
            {s.docs_url && <a href={s.docs_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-brand-600 hover:underline mt-3">API docs <ExternalLink size={11} /></a>}
          </Card>
        ))}
      </div>
    </div>
  );
}
