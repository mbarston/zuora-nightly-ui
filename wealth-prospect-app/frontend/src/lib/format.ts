import type { Persona } from "./api";

export const money = (n: number | null | undefined, compact = true): string => {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (!compact) return "$" + Math.round(n).toLocaleString();
  const abs = Math.abs(n);
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(abs >= 1e7 ? 0 : 1)}M`;
  if (abs >= 1e3) return `$${Math.round(n / 1e3)}K`;
  return `$${Math.round(n)}`;
};

export const date = (s: string | null | undefined): string => {
  if (!s) return "—";
  const d = new Date(s.length <= 10 ? s + "T00:00:00" : s);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
};

export const relTime = (s: string | null | undefined): string => {
  if (!s) return "never";
  const d = new Date(s.length <= 10 ? s + "T00:00:00" : s).getTime();
  const days = Math.round((Date.now() - d) / 86400000);
  if (days < 0) return `in ${-days}d`;
  if (days === 0) return "today";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.round(days / 30)}mo ago`;
  return `${(days / 365).toFixed(1)}y ago`;
};

export const TIER: Record<string, { label: string; full: string; cls: string }> = {
  ultra: { label: "UHNW", full: "Ultra-high net worth ($30M+)", cls: "bg-violet-100 text-violet-800 ring-violet-200" },
  vhnw: { label: "VHNW", full: "Very high net worth ($5M–$30M)", cls: "bg-indigo-100 text-indigo-800 ring-indigo-200" },
  hnw: { label: "HNW", full: "High net worth ($1M–$5M)", cls: "bg-sky-100 text-sky-800 ring-sky-200" },
  affluent: { label: "Affluent", full: "Affluent ($250K–$1M)", cls: "bg-emerald-100 text-emerald-800 ring-emerald-200" },
  mass: { label: "Mass", full: "Mass market (<$250K)", cls: "bg-slate-100 text-slate-700 ring-slate-200" },
};

export const PERSONA_LABEL: Record<Persona, string> = {
  realtor: "Realtor", wealth_manager: "Wealth Manager", financial_planner: "Financial Planner",
};

export const scoreOf = (s: { realtor_score: number; wealth_manager_score: number; financial_planner_score: number } | null | undefined, p: Persona): number =>
  s ? s[`${p}_score`] : 0;

export const scoreCls = (n: number): string =>
  n >= 70 ? "bg-emerald-500" : n >= 45 ? "bg-amber-500" : "bg-slate-300";

export const scoreText = (n: number): string =>
  n >= 70 ? "text-emerald-700" : n >= 45 ? "text-amber-700" : "text-slate-500";

export const STAGES = ["new", "researching", "contacted", "meeting", "client", "lost"] as const;

export const STAGE_CLS: Record<string, string> = {
  new: "bg-slate-100 text-slate-700", researching: "bg-sky-100 text-sky-800", contacted: "bg-amber-100 text-amber-800",
  meeting: "bg-violet-100 text-violet-800", client: "bg-emerald-100 text-emerald-800", lost: "bg-red-100 text-red-700",
};

export const SOURCE_LABEL: Record<string, string> = {
  property_records: "Property records", sec_edgar: "SEC EDGAR", fec: "FEC", business_registry: "Business registry",
  nonprofit_990: "Nonprofit 990", employment: "Employment", demographics: "Demographics", life_events: "Life events",
};

export const KIND_LABEL: Record<string, string> = {
  "property.owned": "Owns property", "property.listed": "Home listed", "property.sold": "Property sold",
  "equity.insider_holding": "Insider holding", "equity.insider_transaction": "Insider transaction", "equity.ipo_lockup": "IPO lockup",
  "business.ownership": "Business ownership", "business.exit": "Business exit", "donation.political": "Political gift",
  "donation.charitable": "Charitable gift", "board.membership": "Board seat", "employment.title": "Employment",
  "employment.change": "Job change", "demographic.household": "Household", life_event: "Life event", "advisor.relationship": "Has advisor",
};

export const TRIGGER_LABEL: Record<string, string> = {
  listed_home: "Listed home", sold_home: "Sold home", bought_home: "Bought home", insider_sale: "Insider sale",
  lockup_expiry: "Lockup expiry", business_exit: "Business exit", new_business: "New business", job_change: "Job change",
  life_inheritance: "Inheritance", life_retirement: "Retirement", life_divorce: "Divorce", life_marriage: "Marriage",
  life_birth: "New child", life_relocation: "Relocation", life_probate: "Probate", major_gift: "Major gift",
};
