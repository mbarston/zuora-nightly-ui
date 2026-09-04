import clsx from "clsx";
import type { ReactNode } from "react";
import { Flame, Zap } from "lucide-react";
import type { Persona, Trigger } from "@/lib/api";
import { PERSONA_LABEL, scoreCls, scoreText, STAGE_CLS, TIER } from "@/lib/format";

export function Card({ children, className, title, action }: { children: ReactNode; className?: string; title?: ReactNode; action?: ReactNode }) {
  return (
    <section className={clsx("card", className)}>
      {(title || action) && (
        <header className="flex items-center justify-between px-5 pt-4 pb-2">
          <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
          {action}
        </header>
      )}
      <div className={clsx(title ? "px-5 pb-5" : "p-5")}>{children}</div>
    </section>
  );
}

export function Badge({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={clsx("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset", className)}>{children}</span>;
}

export function TierBadge({ tier }: { tier: string | undefined }) {
  const t = TIER[tier ?? "mass"] ?? TIER.mass;
  return <Badge className={t.cls}><span title={t.full}>{t.label}</span></Badge>;
}

export function StageBadge({ stage }: { stage: string }) {
  return <span className={clsx("inline-flex rounded-md px-2 py-0.5 text-xs font-medium capitalize", STAGE_CLS[stage] ?? STAGE_CLS.new)}>{stage}</span>;
}

export function ScorePill({ value, size = "md" }: { value: number; size?: "sm" | "md" | "lg" }) {
  const dims = size === "lg" ? "h-12 w-12 text-lg" : size === "sm" ? "h-7 w-7 text-xs" : "h-9 w-9 text-sm";
  return (
    <span className={clsx("inline-flex items-center justify-center rounded-full font-bold text-white tabular-nums", dims, scoreCls(value))}>
      {value}
    </span>
  );
}

export function ScoreBar({ value, label }: { value: number; label?: string }) {
  return (
    <div className="flex items-center gap-2 min-w-[120px]">
      <div className="flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
        <div className={clsx("h-full rounded-full", scoreCls(value))} style={{ width: `${value}%` }} />
      </div>
      <span className={clsx("text-sm font-semibold tabular-nums w-7 text-right", scoreText(value))}>{value}</span>
      {label && <span className="text-xs text-slate-500">{label}</span>}
    </div>
  );
}

export function TriggerChip({ t, compact = false }: { t: Trigger; compact?: boolean }) {
  const hot = t.urgency === "hot";
  return (
    <span
      title={`${t.label} · ${t.date}`}
      className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        hot ? "bg-red-50 text-red-700 ring-1 ring-inset ring-red-200" : "bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200")}>
      {hot ? <Flame size={11} /> : <Zap size={11} />}
      {compact ? (t.short ?? t.label) : t.label}
    </span>
  );
}

export function PersonaSwitch({ value, onChange }: { value: Persona; onChange: (p: Persona) => void }) {
  const opts: Persona[] = ["realtor", "wealth_manager", "financial_planner"];
  return (
    <div className="inline-flex rounded-lg bg-slate-100 p-0.5">
      {opts.map((p) => (
        <button key={p} onClick={() => onChange(p)}
          className={clsx("px-3 py-1 text-xs font-medium rounded-md transition-colors",
            value === p ? "bg-white shadow-sm text-slate-900" : "text-slate-600 hover:text-slate-900")}>
          {PERSONA_LABEL[p]}
        </button>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-sm text-slate-500 py-10 text-center">{children}</div>;
}

export function Spinner() {
  return <div className="flex justify-center py-12"><div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-200 border-t-brand-600" /></div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  return <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{String((error as Error)?.message ?? error)}</div>;
}

export function Stat({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: ReactNode; accent?: string }) {
  return (
    <div className="card p-4">
      <div className="kicker">{label}</div>
      <div className={clsx("mt-1 text-2xl font-semibold tabular-nums", accent)}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}
