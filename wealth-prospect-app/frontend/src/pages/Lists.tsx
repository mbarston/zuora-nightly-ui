import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import clsx from "clsx";
import { Download, Plus, Trash2, X } from "lucide-react";
import { api, type Persona } from "@/lib/api";
import { money, PERSONA_LABEL, scoreOf } from "@/lib/format";
import { Card, Empty, ErrorBox, ScoreBar, Spinner, StageBadge, TierBadge, TriggerChip } from "@/components/ui";

export default function Lists() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const lists = useQuery({ queryKey: ["lists"], queryFn: api.lists });
  const activeId = id ? Number(id) : lists.data?.[0]?.id;
  const active = lists.data?.find((l) => l.id === activeId);
  const members = useQuery({ queryKey: ["list-members", activeId], queryFn: () => api.listMembers(activeId!), enabled: !!activeId });
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<{ name: string; description: string; persona: Persona }>({ name: "", description: "", persona: "wealth_manager" });
  const create = useMutation({ mutationFn: () => api.createList(form), onSuccess: (l) => { qc.invalidateQueries({ queryKey: ["lists"] }); setCreating(false); setForm({ name: "", description: "", persona: "wealth_manager" }); nav(`/lists/${l.id}`); } });
  const remove = useMutation({ mutationFn: (pid: number) => api.removeMember(activeId!, pid), onSuccess: () => { qc.invalidateQueries({ queryKey: ["lists"] }); qc.invalidateQueries({ queryKey: ["list-members", activeId] }); } });
  const del = useMutation({ mutationFn: () => api.deleteList(activeId!), onSuccess: () => { qc.invalidateQueries({ queryKey: ["lists"] }); nav("/lists"); } });

  return (
    <div className="max-w-7xl grid lg:grid-cols-[260px_1fr] gap-5">
      <div className="space-y-3">
        <div className="flex items-center justify-between"><h1 className="text-xl font-semibold">Lists</h1><button className="btn-primary" onClick={() => setCreating(true)}><Plus size={14} /> New</button></div>
        {lists.isLoading ? <Spinner /> : (
          <ul className="space-y-1">
            {lists.data?.map((l) => (
              <li key={l.id}>
                <Link to={`/lists/${l.id}`} className={clsx("block rounded-lg px-3 py-2 border", l.id === activeId ? "bg-white border-brand-300 shadow-card" : "border-transparent hover:bg-white")}>
                  <div className="text-sm font-medium">{l.name}</div>
                  <div className="text-xs text-slate-500">{l.member_count} · {PERSONA_LABEL[l.persona]}</div>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {creating && (
          <div className="card p-4 space-y-2">
            <input className="input" placeholder="List name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <input className="input" placeholder="Description (optional)" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <select className="input" value={form.persona} onChange={(e) => setForm({ ...form, persona: e.target.value as Persona })}>
              {(["realtor", "wealth_manager", "financial_planner"] as Persona[]).map((p) => <option key={p} value={p}>{PERSONA_LABEL[p]}</option>)}
            </select>
            {create.error && <ErrorBox error={create.error} />}
            <div className="flex gap-2 justify-end"><button className="btn-secondary" onClick={() => setCreating(false)}>Cancel</button><button className="btn-primary" disabled={!form.name} onClick={() => create.mutate()}>Create</button></div>
          </div>
        )}
      </div>

      <div>
        {!active ? <Empty>Create a list to start building outreach segments.</Empty> : (
          <Card title={<span>{active.name} <span className="text-slate-400 font-normal">· {active.member_count} · ranked for {PERSONA_LABEL[active.persona]}</span></span>}
            action={<div className="flex gap-2">
              <a href={`/api/lists/${active.id}/export.csv`} className="btn-secondary"><Download size={14} /> Export CSV</a>
              <button className="btn-ghost text-red-600" onClick={() => { if (confirm("Delete this list?")) del.mutate(); }}><Trash2 size={14} /></button>
            </div>}>
            {active.description && <p className="text-sm text-slate-500 mb-3">{active.description}</p>}
            <p className="text-xs text-slate-400 mb-3">Exports automatically exclude anyone on the suppression list and include each person's next-best action for this persona.</p>
            {members.isLoading ? <Spinner /> : !members.data?.items.length ? <Empty>No members yet. Select prospects in the Prospects view and add them here.</Empty> : (
              <table className="w-full">
                <thead><tr><th className="table-head">Prospect</th><th className="table-head">Score</th><th className="table-head">Triggers</th><th className="table-head">Tier</th><th className="table-head text-right">Net worth</th><th className="table-head">Stage</th><th className="table-head" /></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {[...members.data.items].sort((a, b) => scoreOf(b.score, active.persona) - scoreOf(a.score, active.persona)).map((p) => (
                    <tr key={p.id} className="hover:bg-slate-50">
                      <td className="table-cell"><Link to={`/prospects/${p.id}`} className="font-medium hover:text-brand-600">{p.first_name} {p.last_name}</Link><div className="text-xs text-slate-500">{[p.title, p.city].filter(Boolean).join(" · ")}</div></td>
                      <td className="table-cell"><ScoreBar value={scoreOf(p.score, active.persona)} /></td>
                      <td className="table-cell"><div className="flex gap-1 flex-wrap">{p.score?.triggers.slice(0, 2).map((t) => <TriggerChip key={t.key + t.date} t={t} compact />)}</div></td>
                      <td className="table-cell"><TierBadge tier={p.score?.wealth_tier} /></td>
                      <td className="table-cell text-right tabular-nums">{money(p.score?.net_worth_p50)}</td>
                      <td className="table-cell"><StageBadge stage={p.stage} /></td>
                      <td className="table-cell"><button className="btn-ghost text-xs" onClick={() => remove.mutate(p.id)}><X size={12} /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        )}
      </div>
    </div>
  );
}
