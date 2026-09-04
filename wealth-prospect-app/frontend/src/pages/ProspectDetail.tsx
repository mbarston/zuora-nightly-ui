import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import clsx from "clsx";
import { ArrowLeft, ExternalLink, RefreshCw, ShieldOff, Trash2 } from "lucide-react";
import { api, type Factor, type Persona, type ProspectDetail, type Signal } from "@/lib/api";
import { date, KIND_LABEL, money, PERSONA_LABEL, relTime, scoreOf, SOURCE_LABEL, STAGES, TIER } from "@/lib/format";
import { usePersona } from "@/lib/persona";
import { Badge, Card, ErrorBox, PersonaSwitch, ScorePill, Spinner, StageBadge, TierBadge, TriggerChip } from "@/components/ui";

export default function ProspectDetailPage() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const qc = useQueryClient();
  const { persona: globalPersona } = usePersona();
  const [persona, setPersona] = useState<Persona>(globalPersona);
  const [highlight, setHighlight] = useState<number[]>([]);
  const q = useQuery({ queryKey: ["prospect", id], queryFn: () => api.prospect(id) });
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["prospect", id] }); qc.invalidateQueries({ queryKey: ["prospects"] }); qc.invalidateQueries({ queryKey: ["stats"] }); };
  const enrich = useMutation({ mutationFn: () => api.enrich(id), onSuccess: invalidate });
  const patch = useMutation({ mutationFn: (b: Record<string, unknown>) => api.patchProspect(id, b), onSuccess: invalidate });
  const suppress = useMutation({
    mutationFn: () => api.addSuppression({ email: q.data?.email ?? undefined, full_name: `${q.data?.first_name} ${q.data?.last_name}`, zip: q.data?.zip ?? undefined, reason: "opt_out" }),
    onSuccess: invalidate,
  });
  const del = useMutation({ mutationFn: () => api.deleteProspect(id), onSuccess: () => { invalidate(); nav("/prospects"); } });

  if (q.isLoading) return <Spinner />;
  if (q.error || !q.data) return <ErrorBox error={q.error ?? "Not found"} />;
  const p = q.data;
  const s = p.score;
  const ex = p.explanation;
  const pe = ex?.personas?.[persona];

  return (
    <div className="max-w-7xl space-y-5">
      <Link to="/prospects" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-900"><ArrowLeft size={14} /> Prospects</Link>

      {p.suppressed && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 flex items-center gap-2">
          <ShieldOff size={16} /> This person is on the suppression list. They are hidden from lists and exports. Manage in <Link to="/compliance" className="underline">Compliance</Link>.
        </div>
      )}

      <div className="card p-5 flex flex-wrap items-start gap-6">
        <div className="flex-1 min-w-[260px]">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold">{p.first_name} {p.last_name}</h1>
            <TierBadge tier={s?.wealth_tier} />
            <StageBadge stage={p.stage} />
          </div>
          <div className="text-sm text-slate-600 mt-1">{[p.title, p.employer].filter(Boolean).join(" · ") || "No employment on record"}</div>
          <div className="text-sm text-slate-500">{[p.street, p.city, p.state, p.zip].filter(Boolean).join(", ") || "No address"}{p.age_band ? ` · age ${p.age_band}` : ""}</div>
          <div className="text-xs text-slate-400 mt-1">{p.email ?? "no email"}{p.phone ? ` · ${p.phone}` : ""} · source: {p.source} · enriched {relTime(p.last_enriched_at)}</div>
          <div className="flex flex-wrap gap-1.5 mt-3">{s?.triggers.map((t) => <TriggerChip key={t.key + t.date} t={t} />)}</div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex gap-2">
            <select className="input w-auto" value={p.stage} onChange={(e) => patch.mutate({ stage: e.target.value })}>
              {STAGES.map((st) => <option key={st} value={st}>{st}</option>)}
            </select>
            <button className="btn-secondary" onClick={() => enrich.mutate()} disabled={enrich.isPending}><RefreshCw size={14} className={clsx(enrich.isPending && "animate-spin")} /> Re-enrich</button>
          </div>
          <div className="flex gap-2">
            <AddToList prospectId={p.id} current={p.lists} />
            {!p.suppressed && <button className="btn-ghost text-xs" onClick={() => suppress.mutate()}><ShieldOff size={12} /> Opt out</button>}
            <button className="btn-ghost text-xs text-red-600" onClick={() => { if (confirm("Delete this prospect and all their signals?")) del.mutate(); }}><Trash2 size={12} /> Delete</button>
          </div>
          {p.lists.length > 0 && <div className="text-xs text-slate-500">In: {p.lists.map((l) => <Link key={l.id} to={`/lists/${l.id}`} className="underline ml-1">{l.name}</Link>)}</div>}
        </div>
      </div>

      {!s ? <ErrorBox error="Not scored yet — click Re-enrich." /> : (
        <div className="grid lg:grid-cols-3 gap-5">
          <div className="lg:col-span-2 space-y-5">
            <Card title={<span>Fit for <span className="text-brand-600">{PERSONA_LABEL[persona]}</span></span>} action={<PersonaSwitch value={persona} onChange={setPersona} />}>
              <div className="flex gap-6 items-start">
                <div className="text-center">
                  <ScorePill value={scoreOf(s, persona)} size="lg" />
                  <div className="text-[10px] text-slate-500 mt-1">of 100</div>
                </div>
                <div className="flex-1">
                  <div className="rounded-lg bg-brand-50 border border-brand-100 px-4 py-3 text-sm text-brand-900 mb-4">
                    <span className="font-semibold">Next best action: </span>{pe?.next_best_action}
                  </div>
                  <FactorTable factors={pe?.factors ?? []} unit="pts" onHover={setHighlight} />
                </div>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                {(["realtor", "wealth_manager", "financial_planner"] as Persona[]).map((k) => (
                  <button key={k} onClick={() => setPersona(k)} className={clsx("rounded-lg border px-3 py-2", k === persona ? "border-brand-300 bg-brand-50" : "border-slate-200 hover:bg-slate-50")}>
                    <div className="text-[11px] text-slate-500">{PERSONA_LABEL[k]}</div>
                    <div className="text-lg font-semibold tabular-nums">{scoreOf(s, k)}</div>
                  </button>
                ))}
              </div>
            </Card>

            <Card title="Estimated wealth" action={<span className="text-xs text-slate-500">confidence {(s.confidence * 100).toFixed(0)}% · {TIER[s.wealth_tier].full}</span>}>
              <div className="flex items-baseline gap-3 mb-2">
                <span className="text-3xl font-semibold tabular-nums">{money(s.net_worth_p50)}</span>
                <span className="text-sm text-slate-500">likely range {money(s.net_worth_p10)} – {money(s.net_worth_p90)}</span>
              </div>
              <RangeBar p10={s.net_worth_p10} p50={s.net_worth_p50} p90={s.net_worth_p90} />
              <Composition s={s} />
              <div className="grid grid-cols-3 gap-3 mt-4 text-sm">
                <div className="rounded-lg bg-slate-50 p-3"><div className="kicker">Investable assets</div><div className="text-lg font-semibold tabular-nums">{money(s.investable_assets)}</div><div className="text-[11px] text-slate-500">liquid + 80% of marketable stock</div></div>
                <div className="rounded-lg bg-slate-50 p-3"><div className="kicker">Est. income</div><div className="text-lg font-semibold tabular-nums">{money(s.income_estimate)}/yr</div></div>
                <div className="rounded-lg bg-slate-50 p-3"><div className="kicker">Data coverage</div><div className="flex flex-wrap gap-1 mt-1">{Object.entries(ex.wealth.coverage ?? {}).map(([k, v]) => <span key={k} className={clsx("text-[10px] px-1.5 py-0.5 rounded", v ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-400 line-through")}>{k}</span>)}</div></div>
              </div>
              <div className="mt-4"><div className="kicker mb-2">How we got there</div><FactorTable factors={ex.wealth.factors} unit="$" onHover={setHighlight} /></div>
            </Card>
          </div>

          <div className="space-y-5">
            <Card title={`Evidence (${p.signals.length} signals)`}>
              <SignalList signals={p.signals} highlight={highlight} />
            </Card>
            <ActivityPanel p={p} onChange={invalidate} />
          </div>
        </div>
      )}
    </div>
  );
}

function RangeBar({ p10, p50, p90 }: { p10: number; p50: number; p90: number }) {
  const max = Math.max(p90, 1);
  return (
    <div className="relative h-3 rounded-full bg-slate-100 my-3">
      <div className="absolute h-full rounded-full bg-brand-100" style={{ left: `${(p10 / max) * 100}%`, width: `${((p90 - p10) / max) * 100}%` }} />
      <div className="absolute top-1/2 -translate-y-1/2 h-4 w-1 rounded bg-brand-600" style={{ left: `${(p50 / max) * 100}%` }} />
    </div>
  );
}

function Composition({ s }: { s: NonNullable<ProspectDetail["score"]> }) {
  const parts = [
    { k: "Real estate equity", v: s.real_estate_equity, c: "bg-sky-500" },
    { k: "Private business", v: s.business_equity, c: "bg-violet-500" },
    { k: "Public equity", v: s.public_equity, c: "bg-indigo-500" },
    { k: "Liquid financial", v: s.financial_assets, c: "bg-emerald-500" },
  ];
  const total = Math.max(1, parts.reduce((a, b) => a + b.v, 0));
  return (
    <div>
      <div className="flex h-3 rounded-full overflow-hidden mt-2">
        {parts.map((x) => <div key={x.k} className={x.c} style={{ width: `${(x.v / total) * 100}%` }} title={`${x.k}: ${money(x.v)}`} />)}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs text-slate-600">
        {parts.map((x) => <span key={x.k} className="flex items-center gap-1.5"><span className={clsx("h-2 w-2 rounded-sm", x.c)} />{x.k} <span className="font-medium tabular-nums">{money(x.v)}</span></span>)}
      </div>
    </div>
  );
}

function FactorTable({ factors, unit, onHover }: { factors: Factor[]; unit: "pts" | "$"; onHover: (ids: number[]) => void }) {
  if (!factors.length) return <div className="text-sm text-slate-500">No contributing factors.</div>;
  return (
    <ul className="divide-y divide-slate-100">
      {factors.map((f, i) => (
        <li key={i} className="flex items-start gap-3 py-1.5 -mx-2 px-2 rounded hover:bg-slate-50 cursor-default"
          onMouseEnter={() => onHover(f.signal_ids)} onMouseLeave={() => onHover([])}>
          <span className={clsx("w-16 shrink-0 text-right font-semibold tabular-nums text-sm", f.value < 0 ? "text-red-600" : f.value === 0 ? "text-slate-400" : "text-slate-800")}>
            {unit === "$" ? money(f.value) : `${f.value > 0 ? "+" : ""}${Math.round(f.value)}`}
          </span>
          <span className="min-w-0">
            <span className="text-sm font-medium">{f.label}</span>
            <span className="block text-xs text-slate-500">{f.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function SignalList({ signals, highlight }: { signals: Signal[]; highlight: number[] }) {
  if (!signals.length) return <div className="text-sm text-slate-500">No signals yet. Run enrichment.</div>;
  return (
    <ul className="space-y-2 max-h-[640px] overflow-y-auto -mr-2 pr-2">
      {signals.map((s) => {
        const hi = highlight.includes(s.id);
        return (
          <li key={s.id} className={clsx("rounded-lg border px-3 py-2 transition-colors", hi ? "border-brand-400 bg-brand-50" : "border-slate-100")}>
            <div className="flex items-center justify-between gap-2">
              <Badge className="bg-slate-50 text-slate-700 ring-slate-200">{KIND_LABEL[s.kind] ?? s.kind}</Badge>
              <span className="text-[11px] text-slate-400 whitespace-nowrap">{date(s.observed_at)}</span>
            </div>
            <div className="text-sm mt-1">{s.summary}</div>
            <div className="flex items-center justify-between mt-1 text-[11px] text-slate-500">
              <span>{SOURCE_LABEL[s.source] ?? s.source} · {(s.confidence * 100).toFixed(0)}% conf.</span>
              {s.source_ref && (s.source_ref.startsWith("http")
                ? <a href={s.source_ref} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-brand-600 hover:underline">source <ExternalLink size={10} /></a>
                : <span className="truncate max-w-[140px]" title={s.source_ref}>{s.source_ref}</span>)}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function ActivityPanel({ p, onChange }: { p: ProspectDetail; onChange: () => void }) {
  const [kind, setKind] = useState("note");
  const [body, setBody] = useState("");
  const m = useMutation({ mutationFn: () => api.addActivity(p.id, { kind, body }), onSuccess: () => { setBody(""); onChange(); } });
  return (
    <Card title="Activity">
      <div className="flex gap-2 mb-3">
        <select className="input w-auto" value={kind} onChange={(e) => setKind(e.target.value)}>
          {["note", "call", "email", "meeting"].map((k) => <option key={k}>{k}</option>)}
        </select>
        <input className="input" placeholder="Log a note or touchpoint…" value={body} onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && body) m.mutate(); }} />
        <button className="btn-primary" disabled={!body || m.isPending} onClick={() => m.mutate()}>Log</button>
      </div>
      <ul className="space-y-2 max-h-72 overflow-y-auto">
        {p.activities.map((a) => (
          <li key={a.id} className="text-sm">
            <span className="text-[11px] uppercase tracking-wide text-slate-400 mr-2">{a.kind}</span>{a.body}
            <div className="text-[11px] text-slate-400">{a.author ? `${a.author} · ` : ""}{relTime(a.created_at)}</div>
          </li>
        ))}
        {!p.activities.length && <li className="text-sm text-slate-500">No activity yet.</li>}
      </ul>
    </Card>
  );
}

function AddToList({ prospectId, current }: { prospectId: number; current: { id: number }[] }) {
  const qc = useQueryClient();
  const lists = useQuery({ queryKey: ["lists"], queryFn: api.lists });
  const m = useMutation({ mutationFn: (listId: number) => api.addMembers(listId, [prospectId]),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["lists"] }); qc.invalidateQueries({ queryKey: ["prospect", prospectId] }); } });
  const inIds = new Set(current.map((l) => l.id));
  return (
    <select className="input w-auto text-xs" value="" onChange={(e) => { if (e.target.value) m.mutate(Number(e.target.value)); }}>
      <option value="">Add to list…</option>
      {lists.data?.filter((l) => !inIds.has(l.id)).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
    </select>
  );
}
