export type Persona = "realtor" | "wealth_manager" | "financial_planner";

export interface Trigger { key: string; label: string; short?: string; signal_id: number | null; urgency: "hot" | "warm"; date: string }

export interface Score {
  computed_at: string;
  net_worth_p10: number; net_worth_p50: number; net_worth_p90: number;
  investable_assets: number; income_estimate: number;
  real_estate_equity: number; business_equity: number; public_equity: number; financial_assets: number;
  confidence: number;
  realtor_score: number; wealth_manager_score: number; financial_planner_score: number;
  wealth_tier: "ultra" | "vhnw" | "hnw" | "affluent" | "mass";
  triggers: Trigger[];
}

export interface ProspectRow {
  id: number; first_name: string; last_name: string; email: string | null;
  city: string | null; state: string | null; zip: string | null; age_band: string | null;
  employer: string | null; title: string | null; owner: string | null; stage: string;
  tags: string[]; suppressed: boolean; source: string; last_enriched_at: string | null;
  score: Score | null;
}

export interface Signal {
  id: number; kind: string; source: string; source_ref: string | null; confidence: number;
  observed_at: string; summary: string; data: Record<string, unknown>;
}

export interface Activity { id: number; kind: string; body: string; author: string | null; created_at: string }

export interface Factor { name: string; label: string; value: number; detail: string; signal_ids: number[] }

export interface Explanation {
  wealth: Score & { coverage: Record<string, boolean>; factors: Factor[] };
  personas: Record<Persona, { score: number; next_best_action: string; factors: Factor[] }>;
  triggers: Trigger[];
}

export interface ProspectDetail extends ProspectRow {
  phone: string | null; street: string | null; created_at: string;
  signals: Signal[]; activities: Activity[]; explanation: Explanation; lists: { id: number; name: string }[];
}

export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export interface ListOut { id: number; name: string; description: string | null; persona: Persona; created_at: string; member_count: number }

export interface Stats {
  prospects: number; suppressed: number; hot_prospects: number; new_triggers_7d: number;
  total_net_worth_p50: number; avg_confidence: number;
  tiers: Record<string, number>; triggers: [string, number][];
  score_distribution: Record<Persona, number[]>; stages: Record<string, number>;
  signals_by_source: Record<string, number>; signals_total: number;
}

export interface Source {
  key: string; name: string; category: string; description: string; legal_basis: string; cost: string;
  coverage: string; refresh: string; signal_kinds: string[]; signal_labels: string[]; docs_url: string | null;
  mode: "live" | "synthetic" | "planned"; supports_live: boolean; signal_count: number; last_observed: string | null;
}

export interface Suppression { id: number; email: string | null; full_name: string | null; zip: string | null; reason: string; note: string | null; created_at: string }

export interface PersonaDef { label: string; question: string; score_field: string; primary_metric: string; weights: Record<string, number> }

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }, ...init });
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j); } catch { /* ignore */ }
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

const qs = (o: Record<string, unknown>) =>
  Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== "" && v !== false)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&");

export const api = {
  stats: () => req<Stats>("/api/stats"),
  personas: () => req<Record<Persona, PersonaDef>>("/api/prospects/meta/personas"),
  prospects: (params: Record<string, unknown>) => req<Page<ProspectRow>>(`/api/prospects?${qs(params)}`),
  prospect: (id: number) => req<ProspectDetail>(`/api/prospects/${id}`),
  createProspect: (body: Record<string, unknown>) => req<ProspectRow>("/api/prospects", { method: "POST", body: JSON.stringify(body) }),
  patchProspect: (id: number, body: Record<string, unknown>) => req<ProspectRow>(`/api/prospects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProspect: (id: number) => req<void>(`/api/prospects/${id}`, { method: "DELETE" }),
  enrich: (id: number) => req<ProspectDetail>(`/api/prospects/${id}/enrich`, { method: "POST" }),
  addActivity: (id: number, body: { kind: string; body: string; author?: string }) =>
    req<Activity>(`/api/prospects/${id}/activities`, { method: "POST", body: JSON.stringify(body) }),
  importCsv: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/prospects/import", { method: "POST", body: fd });
    if (!res.ok) throw new Error(await res.text());
    return res.json() as Promise<{ created: number; skipped_duplicates: number; errors: string[] }>;
  },
  lists: () => req<ListOut[]>("/api/lists"),
  createList: (body: { name: string; description?: string; persona: Persona }) => req<ListOut>("/api/lists", { method: "POST", body: JSON.stringify(body) }),
  deleteList: (id: number) => req<void>(`/api/lists/${id}`, { method: "DELETE" }),
  listMembers: (id: number) => req<Page<ProspectRow>>(`/api/lists/${id}/members`),
  addMembers: (id: number, prospect_ids: number[]) => req<ListOut>(`/api/lists/${id}/members`, { method: "POST", body: JSON.stringify({ prospect_ids }) }),
  removeMember: (id: number, pid: number) => req<ListOut>(`/api/lists/${id}/members/${pid}`, { method: "DELETE" }),
  sources: () => req<{ live_connectors: boolean; sources: Source[] }>("/api/sources"),
  compliance: () => req<{ permissible_use: string; suppressions: Suppression[] }>("/api/compliance"),
  addSuppression: (body: Partial<Suppression>) => req<Suppression>("/api/compliance/suppressions", { method: "POST", body: JSON.stringify(body) }),
  removeSuppression: (id: number) => req<void>(`/api/compliance/suppressions/${id}`, { method: "DELETE" }),
};
