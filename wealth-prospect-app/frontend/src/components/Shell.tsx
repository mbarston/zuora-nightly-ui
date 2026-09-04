import { NavLink, Outlet } from "react-router-dom";
import clsx from "clsx";
import { BarChart3, Database, ListChecks, ShieldCheck, Upload, Users } from "lucide-react";
import { usePersona } from "@/lib/persona";
import { PersonaSwitch } from "./ui";

const NAV = [
  { to: "/", label: "Dashboard", icon: BarChart3, end: true },
  { to: "/prospects", label: "Prospects", icon: Users },
  { to: "/lists", label: "Lists", icon: ListChecks },
  { to: "/import", label: "Import", icon: Upload },
  { to: "/sources", label: "Data sources", icon: Database },
  { to: "/compliance", label: "Compliance", icon: ShieldCheck },
];

export default function Shell() {
  const { persona, setPersona } = usePersona();
  return (
    <div className="flex h-full">
      <aside className="w-56 shrink-0 bg-ink-950 text-slate-300 flex flex-col">
        <div className="px-5 py-5 flex items-center gap-2">
          <div className="h-7 w-7 rounded-lg bg-brand-500 grid place-items-center text-white font-bold text-sm">P</div>
          <div>
            <div className="text-white font-semibold leading-tight">Prospect Lens</div>
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Wealth intelligence</div>
          </div>
        </div>
        <nav className="px-3 space-y-0.5">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => clsx("flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm",
                isActive ? "bg-ink-800 text-white" : "hover:bg-ink-900 hover:text-white")}>
              <Icon size={16} /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto px-5 py-4 text-[11px] text-slate-500 leading-relaxed">
          Prospecting insights only. Not a consumer report. Not for credit, insurance, employment or housing decisions.
        </div>
      </aside>
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="h-14 shrink-0 border-b border-slate-200 bg-white/80 backdrop-blur flex items-center justify-between px-6">
          <div className="text-sm text-slate-500">Viewing as <span className="font-medium text-slate-900">{persona.replace("_", " ")}</span></div>
          <PersonaSwitch value={persona} onChange={setPersona} />
        </header>
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
