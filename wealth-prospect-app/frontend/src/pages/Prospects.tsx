import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Plus, Search, X } from "lucide-react";
import { api, type Persona, type ProspectRow } from "@/lib/api";
import { money, PERSONA_LABEL, scoreOf, STAGES, TIER, TRIGGER_LABEL } from "@/lib/format";
import { usePersona } from "@/lib/persona";
import { Card, Empty, ErrorBox, ScoreBar, Spinner, StageBadge, TierBadge, TriggerChip } from "@/components/ui";

const PAGE = 50;

export default function Prospects() {
  const { persona } = usePersona();
  const [sp, setSp] = useSearchParams();
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [showAdd, setShowAdd] = useState(false);

  const params = useMemo(() => ({
    persona, q: sp.get("q") ?? "", min_score: sp.get("min_score") ?? "", tier: sp.get("tier") ?? "",
    state: sp.get("state") ?? "", stage: sp.get("stage") ?? "", trigger: sp.get("trigger") ?? "",
    hot_only: sp.get("hot_only") === "true", sort: sp.get("sort") ?? "", order: sp.get("order") ?? "desc",
    page: Number(sp.get("page") ?? 1), page_size: PAGE,
  }), [sp, persona]);

  const set = (k: string, v: string | null) => {
    const n = new URLSearchParams(sp);
    if (v === null || v === "" || v === "false") n.delete(k); else n.set(k, v);
    if (k !== "page") n.delete("page");
    setSp(n, { replace: true });
  };

  const q = useQuery({ queryKey: ["prospects", params], queryFn: () => api.prospects(params) });
  const lists = useQuery({ queryKey: ["lists"], queryFn: api.lists });
  const addToList = useMutation({
    mutationFn: ({ listId, ids }: { listId: number; ids: number[] }) => api.addMembers(listId, ids),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["lists"] }); setSelected(new Set()); },
  });

  const toggleSort = (col: string) => {
    if ((params.sort || persona) === col) set("order", params.order === "desc" ? "asc" : "desc");
    else { set("sort", col); }
  };
  const totalPages = Math.max(1, Math.ceil((q.data?.total ?? 0) / PAGE));
  const activeFilters = ["q", "min_score", "tier", "state", "stage", "trigger", "hot_only"].filter((k) => sp.get(k));

  return (
    <div className="space-y-4 max-w-7xl">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Prospects</h1>
          <p className="text-sm text-slate-500">{q.data?.total.toLocaleString() ?? "…"} matching · ranked by {PERSONA_LABEL[persona]} score</p>
        </div>
        <button className="btn-primary" onClick={() => setShowAdd(true)}><Plus size={14} /> Add prospect</button>
      </div>

      <Card className="!p-0">
        <div className="flex flex-wrap items-center gap-2 p-3 border-b border-slate-100">
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-2.5 text-slate-400" />
            <input className="input pl-8 w-64" placeholder="Search name, employer, city…" defaultValue={params.q}
              onKeyDown={(e) => { if (e.key === "Enter") set("q", (e.target as HTMLInputElement).value); }} />
          </div>
          <select className="input w-auto" value={params.min_score} onChange={(e) => set("min_score", e.target.value)}>
            <option value="">Any score</option>
            {[40, 60, 70, 80].map((n) => <option key={n} value={n}>Score ≥ {n}</option>)}
          </select>
          <select className="input w-auto" value={params.tier} onChange={(e) => set("tier", e.target.value)}>
            <option value="">Any tier</option>
            {Object.entries(TIER).map(([k, v]) => <option key={k} value={k}>{v.full}</option>)}
          </select>
          <select className="input w-auto" value={params.stage} onChange={(e) => set("stage", e.target.value)}>
            <option value="">Any stage</option>
            {STAGES.map((s) => <option key={s} value={s} className="capitalize">{s}</option>)}
          </select>
          <select className="input w-auto" value={params.trigger} onChange={(e) => set("trigger", e.target.value)}>
            <option value="">Any trigger</option>
            {Object.entries(TRIGGER_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <input className="input w-20 uppercase" placeholder="State" defaultValue={params.state} maxLength={2}
            onKeyDown={(e) => { if (e.key === "Enter") set("state", (e.target as HTMLInputElement).value); }} />
          <label className="flex items-center gap-1.5 text-sm text-slate-700 px-2">
            <input type="checkbox" checked={params.hot_only} onChange={(e) => set("hot_only", e.target.checked ? "true" : null)} /> Hot only
          </label>
          {activeFilters.length > 0 && (
            <button className="btn-ghost text-xs" onClick={() => setSp(new URLSearchParams(), { replace: true })}><X size={12} /> Clear</button>
          )}
        </div>

        {selected.size > 0 && (
          <div className="flex items-center gap-3 px-3 py-2 bg-brand-50 border-b border-brand-100 text-sm">
            <span className="font-medium">{selected.size} selected</span>
            <select className="input w-auto" defaultValue="" onChange={(e) => { const id = Number(e.target.value); if (id) addToList.mutate({ listId: id, ids: [...selected] }); e.target.value = ""; }}>
              <option value="">Add to list…</option>
              {lists.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
            <button className="btn-ghost text-xs" onClick={() => setSelected(new Set())}>Clear selection</button>
            {addToList.isSuccess && <span className="text-emerald-700 text-xs">Added.</span>}
          </div>
        )}

        {q.isLoading ? <Spinner /> : q.error ? <div className="p-4"><ErrorBox error={q.error} /></div> : !q.data?.items.length ? <Empty>No prospects match. Try clearing filters or importing a list.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-50 border-b border-slate-100">
                <tr>
                  <th className="table-head w-8"><input type="checkbox" checked={selected.size === q.data.items.length}
                    onChange={(e) => setSelected(e.target.checked ? new Set(q.data!.items.map((p) => p.id)) : new Set())} /></th>
                  <th className="table-head cursor-pointer" onClick={() => toggleSort("name")}>Prospect</th>
                  <th className="table-head cursor-pointer" onClick={() => toggleSort(persona)}>{PERSONA_LABEL[persona]} score</th>
                  <th className="table-head">Triggers</th>
                  <th className="table-head">Tier</th>
                  <th className="table-head cursor-pointer text-right" onClick={() => toggleSort("net_worth")}>Net worth</th>
                  <th className="table-head cursor-pointer text-right" onClick={() => toggleSort("investable")}>Investable</th>
                  <th className="table-head">Stage</th>
                  <th className="table-head">Owner</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {q.data.items.map((p) => <Row key={p.id} p={p} persona={persona} checked={selected.has(p.id)}
                  onCheck={(v) => setSelected((s) => { const n = new Set(s); v ? n.add(p.id) : n.delete(p.id); return n; })} />)}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex items-center justify-between px-3 py-2 border-t border-slate-100 text-sm text-slate-500">
          <span>Page {params.page} of {totalPages}</span>
          <div className="flex gap-1">
            <button className="btn-secondary" disabled={params.page <= 1} onClick={() => set("page", String(params.page - 1))}><ChevronLeft size={14} /></button>
            <button className="btn-secondary" disabled={params.page >= totalPages} onClick={() => set("page", String(params.page + 1))}><ChevronRight size={14} /></button>
          </div>
        </div>
      </Card>
      {showAdd && <AddProspect onClose={() => { setShowAdd(false); qc.invalidateQueries({ queryKey: ["prospects"] }); qc.invalidateQueries({ queryKey: ["stats"] }); }} />}
    </div>
  );
}

function Row({ p, persona, checked, onCheck }: { p: ProspectRow; persona: Persona; checked: boolean; onCheck: (v: boolean) => void }) {
  const s = p.score;
  return (
    <tr className="hover:bg-slate-50">
      <td className="table-cell"><input type="checkbox" checked={checked} onChange={(e) => onCheck(e.target.checked)} /></td>
      <td className="table-cell">
        <Link to={`/prospects/${p.id}`} className="font-medium hover:text-brand-600">{p.first_name} {p.last_name}</Link>
        <div className="text-xs text-slate-500 truncate max-w-[260px]">{[p.title, p.employer].filter(Boolean).join(" · ")}{p.city ? ` · ${p.city}, ${p.state}` : ""}</div>
      </td>
      <td className="table-cell"><ScoreBar value={scoreOf(s, persona)} /></td>
      <td className="table-cell"><div className="flex gap-1 flex-wrap max-w-[260px]">{s?.triggers.slice(0, 3).map((t) => <TriggerChip key={t.key + t.date} t={t} compact />)}</div></td>
      <td className="table-cell"><TierBadge tier={s?.wealth_tier} /></td>
      <td className="table-cell text-right tabular-nums">{money(s?.net_worth_p50)}<div className="text-[10px] text-slate-400">{money(s?.net_worth_p10)}–{money(s?.net_worth_p90)}</div></td>
      <td className="table-cell text-right tabular-nums">{money(s?.investable_assets)}</td>
      <td className="table-cell"><StageBadge stage={p.stage} /></td>
      <td className="table-cell text-slate-600 text-xs">{p.owner ?? "—"}</td>
    </tr>
  );
}

function AddProspect({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState({ first_name: "", last_name: "", email: "", city: "", state: "", zip: "", employer: "", title: "" });
  const m = useMutation({ mutationFn: () => api.createProspect({ ...f, state: f.state.toUpperCase() || null }), onSuccess: onClose });
  const F = (k: keyof typeof f, label: string, w = "") => (
    <div className={w}><label className="label">{label}</label><input className="input" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></div>
  );
  return (
    <div className="fixed inset-0 bg-black/30 grid place-items-center z-50" onClick={onClose}>
      <div className="card w-[520px] p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="font-semibold mb-1">Add prospect</h2>
        <p className="text-xs text-slate-500 mb-4">We'll run every enabled data source and score them immediately.</p>
        <div className="grid grid-cols-2 gap-3">
          {F("first_name", "First name")}{F("last_name", "Last name")}
          {F("email", "Email", "col-span-2")}
          {F("city", "City")}<div className="grid grid-cols-2 gap-3">{F("state", "State")}{F("zip", "ZIP")}</div>
          {F("employer", "Employer")}{F("title", "Title")}
        </div>
        {m.error && <div className="mt-3"><ErrorBox error={m.error} /></div>}
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!f.first_name || !f.last_name || m.isPending} onClick={() => m.mutate()}>{m.isPending ? "Enriching…" : "Add & enrich"}</button>
        </div>
      </div>
    </div>
  );
}
