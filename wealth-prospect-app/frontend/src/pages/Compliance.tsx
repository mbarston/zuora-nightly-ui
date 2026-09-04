import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import { Card, ErrorBox, Spinner } from "@/components/ui";

const RULES = [
  ["FCRA", "Outputs are marketing insights, not consumer reports. Never use scores to decide credit, insurance, employment, tenancy or housing eligibility. Contract language and in-app notices reinforce this."],
  ["Fair Housing / ECOA", "Realtor lens targets timing and capacity signals only. No protected-class attributes are stored or inferred, and prospect lists are never used to steer."],
  ["CCPA / CPRA and state privacy laws", "Consumers can request access or deletion. Suppression entries are honoured across search, lists and exports; a deletion request removes the prospect and all signals."],
  ["FEC data", "Federal contribution records are used only as an affluence indicator, never to solicit contributions or build donor lists."],
  ["Court & vital records", "Life-event connectors are gated per jurisdiction because some states restrict commercial use of these records."],
  ["Provenance", "Every signal stores source, reference URL/ID, observation date and confidence — so any prospect can be told exactly what we know and where it came from."],
];

export default function Compliance() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["compliance"], queryFn: api.compliance });
  const [f, setF] = useState({ email: "", full_name: "", zip: "", reason: "opt_out", note: "" });
  const add = useMutation({ mutationFn: () => api.addSuppression({ ...f, email: f.email || null, full_name: f.full_name || null, zip: f.zip || null, note: f.note || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["compliance"] }); qc.invalidateQueries({ queryKey: ["prospects"] }); qc.invalidateQueries({ queryKey: ["stats"] }); setF({ email: "", full_name: "", zip: "", reason: "opt_out", note: "" }); } });
  const remove = useMutation({ mutationFn: (id: number) => api.removeSuppression(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["compliance"] }); qc.invalidateQueries({ queryKey: ["prospects"] }); } });
  if (q.isLoading) return <Spinner />;
  if (q.error || !q.data) return <ErrorBox error={q.error} />;
  return (
    <div className="max-w-5xl space-y-5">
      <div><h1 className="text-xl font-semibold">Compliance</h1><p className="text-sm text-slate-500">Permissible use, opt-outs and the guardrails baked into the product.</p></div>
      <Card title="Permissible use"><p className="text-sm text-slate-700 leading-relaxed">{q.data.permissible_use}</p></Card>
      <Card title="Guardrails">
        <dl className="grid md:grid-cols-2 gap-4">{RULES.map(([k, v]) => <div key={k}><dt className="text-sm font-semibold">{k}</dt><dd className="text-sm text-slate-600 mt-0.5">{v}</dd></div>)}</dl>
      </Card>
      <Card title="Suppression list" action={<span className="text-xs text-slate-500">{q.data.suppressions.length} entries</span>}>
        <div className="grid grid-cols-5 gap-2 mb-4">
          <input className="input" placeholder="Email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          <input className="input" placeholder="Full name" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
          <input className="input" placeholder="ZIP (with name)" value={f.zip} onChange={(e) => setF({ ...f, zip: e.target.value })} />
          <select className="input" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })}>
            {["opt_out", "dnc", "ccpa_delete", "client"].map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <button className="btn-primary justify-center" disabled={(!f.email && !f.full_name) || add.isPending} onClick={() => add.mutate()}>Add</button>
        </div>
        {add.error && <div className="mb-3"><ErrorBox error={add.error} /></div>}
        <table className="w-full">
          <thead><tr><th className="table-head">Email</th><th className="table-head">Name</th><th className="table-head">ZIP</th><th className="table-head">Reason</th><th className="table-head">Added</th><th className="table-head" /></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {q.data.suppressions.map((s) => (
              <tr key={s.id}><td className="table-cell">{s.email ?? "—"}</td><td className="table-cell">{s.full_name ?? "—"}</td><td className="table-cell">{s.zip ?? "—"}</td><td className="table-cell">{s.reason}</td><td className="table-cell text-slate-500">{relTime(s.created_at)}</td>
                <td className="table-cell text-right"><button className="btn-ghost text-xs text-red-600" onClick={() => remove.mutate(s.id)}><Trash2 size={12} /></button></td></tr>
            ))}
            {!q.data.suppressions.length && <tr><td className="table-cell text-slate-500" colSpan={6}>No suppressions yet.</td></tr>}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
