import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowRight, Flame } from "lucide-react";
import { api } from "@/lib/api";
import { money, PERSONA_LABEL, scoreOf, TIER, TRIGGER_LABEL } from "@/lib/format";
import { usePersona } from "@/lib/persona";
import { Card, ErrorBox, ScorePill, Spinner, Stat, TierBadge, TriggerChip } from "@/components/ui";

export default function Dashboard() {
  const { persona } = usePersona();
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  const hot = useQuery({
    queryKey: ["prospects", "hot", persona],
    queryFn: () => api.prospects({ persona, hot_only: true, page_size: 8 }),
  });
  const top = useQuery({
    queryKey: ["prospects", "largest", persona],
    queryFn: () => api.prospects({ persona, sort: "net_worth", page_size: 8 }),
  });
  const personas = useQuery({ queryKey: ["personas"], queryFn: api.personas });

  if (stats.isLoading) return <Spinner />;
  if (stats.error) return <ErrorBox error={stats.error} />;
  const s = stats.data!;
  const dist = s.score_distribution[persona];
  const maxBucket = Math.max(1, ...dist);
  const tierTotal = Math.max(1, Object.values(s.tiers).reduce((a, b) => a + b, 0));

  return (
    <div className="space-y-6 max-w-7xl">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold">Dashboard</h1>
          <p className="text-sm text-slate-500 mt-0.5">{personas.data?.[persona].question}</p>
        </div>
        <Link to="/prospects" className="btn-primary">Open prospects <ArrowRight size={14} /></Link>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Stat label="Prospects" value={s.prospects.toLocaleString()} sub={`${s.suppressed} suppressed`} />
        <Stat label="Hot right now" value={s.hot_prospects} sub="with an active hot trigger" accent="text-red-600" />
        <Stat label="New triggers (7d)" value={s.new_triggers_7d} sub="timing events detected this week" accent="text-amber-600" />
        <Stat label="Est. net worth in book" value={money(s.total_net_worth_p50)} sub={`avg data confidence ${(s.avg_confidence * 100).toFixed(0)}%`} />
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <Card title={`${PERSONA_LABEL[persona]} score distribution`} className="lg:col-span-1">
          <div className="flex items-end gap-1 h-32">
            {dist.map((n, i) => (
              <div key={i} className="flex-1 h-full flex items-end" title={`${i * 10}–${i * 10 + 9}: ${n}`}>
                <div className={`w-full rounded-t ${i >= 7 ? "bg-emerald-500" : i >= 4 ? "bg-amber-400" : "bg-slate-300"}`} style={{ height: `${Math.max(2, (n / maxBucket) * 100)}%` }} />
              </div>
            ))}
          </div>
          <div className="flex justify-between text-[10px] text-slate-400 mt-1"><span>0</span><span>50</span><span>100</span></div>
        </Card>
        <Card title="Wealth tiers" className="lg:col-span-1">
          <div className="flex h-3 rounded-full overflow-hidden">
            {(["ultra", "vhnw", "hnw", "affluent", "mass"] as const).map((t) => (
              <div key={t} title={`${TIER[t].full}: ${s.tiers[t]}`} style={{ width: `${(s.tiers[t] / tierTotal) * 100}%` }}
                className={{ ultra: "bg-violet-500", vhnw: "bg-indigo-500", hnw: "bg-sky-500", affluent: "bg-emerald-500", mass: "bg-slate-300" }[t]} />
            ))}
          </div>
          <ul className="mt-3 space-y-1.5">
            {(["ultra", "vhnw", "hnw", "affluent", "mass"] as const).map((t) => (
              <li key={t} className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-2"><TierBadge tier={t} /><span className="text-slate-500 text-xs">{TIER[t].full}</span></span>
                <Link to={`/prospects?tier=${t}`} className="font-medium tabular-nums hover:underline">{s.tiers[t]}</Link>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Active triggers" className="lg:col-span-1">
          <ul className="space-y-1.5">
            {s.triggers.map(([k, n]) => (
              <li key={k} className="flex items-center justify-between text-sm">
                <Link to={`/prospects?trigger=${k}`} className="hover:underline">{TRIGGER_LABEL[k] ?? k}</Link>
                <span className="font-medium tabular-nums">{n}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card title={<span className="flex items-center gap-1.5"><Flame size={14} className="text-red-500" /> Hot this week</span>}
          action={<Link to="/prospects?hot_only=true" className="text-xs text-brand-600 hover:underline">See all</Link>}>
          <ProspectMini rows={hot.data?.items ?? []} persona={persona} />
        </Card>
        <Card title="Largest balance sheets"
          action={<Link to="/prospects?sort=net_worth" className="text-xs text-brand-600 hover:underline">See all</Link>}>
          <ProspectMini rows={top.data?.items ?? []} persona={persona} />
        </Card>
      </div>
    </div>
  );
}

function ProspectMini({ rows, persona }: { rows: import("@/lib/api").ProspectRow[]; persona: import("@/lib/api").Persona }) {
  if (!rows.length) return <div className="text-sm text-slate-500">Nothing yet.</div>;
  return (
    <ul className="divide-y divide-slate-100 -mx-2">
      {rows.map((p) => (
        <li key={p.id}>
          <Link to={`/prospects/${p.id}`} className="flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-slate-50">
            <ScorePill value={scoreOf(p.score, persona)} size="sm" />
            <div className="min-w-0 flex-1 basis-40">
              <div className="text-sm font-medium truncate">{p.first_name} {p.last_name} <span className="text-slate-400 font-normal">· {p.city}, {p.state}</span></div>
              <div className="text-xs text-slate-500 truncate">{p.title}{p.employer ? ` · ${p.employer}` : ""}</div>
            </div>
            <div className="hidden xl:flex gap-1 shrink-0">{p.score?.triggers.slice(0, 2).map((t) => <TriggerChip key={t.key + t.date} t={t} compact />)}</div>
            <TierBadge tier={p.score?.wealth_tier} />
            <span className="text-sm tabular-nums text-slate-600 w-16 text-right">{money(p.score?.net_worth_p50)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
