import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { FileUp } from "lucide-react";
import { api } from "@/lib/api";
import { Card, ErrorBox } from "@/components/ui";

const SAMPLE = `first_name,last_name,email,city,state,zip,employer,title,age_band,owner,tags
Dana,Whitaker,dana.whitaker@example.com,Austin,TX,78746,Nimbus Data,VP Engineering,45-54,Jordan Lee,referral;event
Priya,Iyer,priya.iyer@example.com,Naples,FL,34102,,Owner & CEO,55-64,,
`;

export default function ImportPage() {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const m = useMutation({ mutationFn: (f: File) => api.importCsv(f), onSuccess: () => { qc.invalidateQueries({ queryKey: ["prospects"] }); qc.invalidateQueries({ queryKey: ["stats"] }); } });
  return (
    <div className="max-w-3xl space-y-5">
      <div><h1 className="text-xl font-semibold">Import prospects</h1><p className="text-sm text-slate-500">Bring your own list — CRM export, event attendees, sphere of influence. Every row is enriched against all enabled data sources and scored on upload.</p></div>
      <Card>
        <label className="flex flex-col items-center justify-center gap-2 border-2 border-dashed border-slate-200 rounded-xl py-10 cursor-pointer hover:border-brand-300 hover:bg-brand-50/30">
          <FileUp className="text-slate-400" />
          <span className="text-sm">{file ? file.name : "Choose a CSV file"}</span>
          <input type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <div className="flex justify-end mt-4"><button className="btn-primary" disabled={!file || m.isPending} onClick={() => file && m.mutate(file)}>{m.isPending ? "Importing & enriching…" : "Import"}</button></div>
        {m.error && <div className="mt-3"><ErrorBox error={m.error} /></div>}
        {m.data && (
          <div className="mt-4 rounded-lg bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-emerald-900">
            Imported <b>{m.data.created}</b> prospects, skipped <b>{m.data.skipped_duplicates}</b> duplicates.
            {m.data.errors.length > 0 && <ul className="mt-2 text-red-700 list-disc pl-5">{m.data.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>}
            <div className="mt-2"><Link to="/prospects?sort=updated" className="underline">View them →</Link></div>
          </div>
        )}
      </Card>
      <Card title="Expected columns">
        <p className="text-sm text-slate-600 mb-3">Header names are case-insensitive and can be in any order. Only <code>first_name</code> and <code>last_name</code> (or a single <code>name</code>) are required — the more you supply (city, state, ZIP, employer, title), the better the matching against public records.</p>
        <pre className="text-xs bg-slate-900 text-slate-100 rounded-lg p-3 overflow-x-auto">{SAMPLE}</pre>
        <p className="text-xs text-slate-500 mt-2">Separate multiple tags with semicolons. Rows whose email already exists are skipped.</p>
      </Card>
    </div>
  );
}
