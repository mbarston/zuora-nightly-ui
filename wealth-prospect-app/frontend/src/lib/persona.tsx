import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Persona } from "./api";

const Ctx = createContext<{ persona: Persona; setPersona: (p: Persona) => void }>({ persona: "wealth_manager", setPersona: () => {} });

export function PersonaProvider({ children }: { children: ReactNode }) {
  const [persona, setPersona] = useState<Persona>(() => {
    try { return (localStorage.getItem("pl.persona") as Persona) || "wealth_manager"; } catch { return "wealth_manager"; }
  });
  useEffect(() => { try { localStorage.setItem("pl.persona", persona); } catch { /* ignore */ } }, [persona]);
  return <Ctx.Provider value={{ persona, setPersona }}>{children}</Ctx.Provider>;
}

export const usePersona = () => useContext(Ctx);
