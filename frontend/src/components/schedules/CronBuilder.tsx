import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/**
 * Dropdown-driven cron builder.
 *
 * Presets: every-n-minutes, hourly, daily, weekly, monthly, custom.
 * Each preset controls a tiny set of dropdowns/inputs and emits the
 * 5-field cron string via `onChange`. Switching presets keeps the
 * generated cron in-sync; switching to "Custom" pre-fills the raw
 * field with whatever the other preset last generated so power users
 * aren't punished for clicking around.
 *
 * Live preview: calls /api/schedules/preview with the current cron and
 * shows the next 3 fire times (or the backend's parse error).
 */

type Preset = "every_n_min" | "hourly" | "daily" | "weekly" | "monthly" | "custom";

const PRESET_LABELS: Record<Preset, string> = {
  every_n_min: "Every N minutes",
  hourly: "Hourly",
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
  custom: "Custom (advanced)",
};

const DOW_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

interface BuilderState {
  preset: Preset;
  everyN: number;            // for every_n_min
  hourlyMinute: number;      // for hourly
  dailyHour: number;         // for daily/weekly
  dailyMinute: number;       // for daily/weekly
  weeklyDays: number[];      // 0-6, for weekly
  monthlyDay: number;        // 1-31 for monthly
  customCron: string;        // raw fallback
}

const DEFAULTS: BuilderState = {
  preset: "daily",
  everyN: 5,
  hourlyMinute: 7,
  dailyHour: 9,
  dailyMinute: 0,
  weeklyDays: [1, 2, 3, 4, 5],
  monthlyDay: 1,
  customCron: "7 9 * * *",
};

export interface CronBuilderProps {
  value: string;                 // current cron string
  onChange: (cron: string) => void;
}

function parseCronIntoState(cron: string, fallback: BuilderState): BuilderState {
  // Best-effort inference from a raw cron string so editing an existing
  // schedule puts you back in the right preset. Unknown shapes fall
  // through to custom.
  const parts = (cron || "").trim().split(/\s+/);
  if (parts.length !== 5) return { ...fallback, preset: "custom", customCron: cron };

  const [min, hr, dom, mon, dow] = parts;

  // every N minutes: "*/N * * * *"
  const everyMatch = min.match(/^\*\/(\d+)$/);
  if (everyMatch && hr === "*" && dom === "*" && mon === "*" && dow === "*") {
    return { ...fallback, preset: "every_n_min", everyN: Number(everyMatch[1]), customCron: cron };
  }
  // hourly: "M * * * *"
  if (/^\d+$/.test(min) && hr === "*" && dom === "*" && mon === "*" && dow === "*") {
    return { ...fallback, preset: "hourly", hourlyMinute: Number(min), customCron: cron };
  }
  // daily: "M H * * *"
  if (/^\d+$/.test(min) && /^\d+$/.test(hr) && dom === "*" && mon === "*" && dow === "*") {
    return {
      ...fallback,
      preset: "daily",
      dailyMinute: Number(min),
      dailyHour: Number(hr),
      customCron: cron,
    };
  }
  // weekly: "M H * * [dow-list]"
  if (/^\d+$/.test(min) && /^\d+$/.test(hr) && dom === "*" && mon === "*" && dow !== "*") {
    let days: number[] = [];
    if (/^\d+(,\d+)*$/.test(dow)) {
      days = dow.split(",").map(Number);
    } else if (/^\d+-\d+$/.test(dow)) {
      const [a, b] = dow.split("-").map(Number);
      for (let d = a; d <= b; d++) days.push(d);
    } else {
      return { ...fallback, preset: "custom", customCron: cron };
    }
    return {
      ...fallback,
      preset: "weekly",
      dailyMinute: Number(min),
      dailyHour: Number(hr),
      weeklyDays: days,
      customCron: cron,
    };
  }
  // monthly: "M H D * *"
  if (/^\d+$/.test(min) && /^\d+$/.test(hr) && /^\d+$/.test(dom) && mon === "*" && dow === "*") {
    return {
      ...fallback,
      preset: "monthly",
      dailyMinute: Number(min),
      dailyHour: Number(hr),
      monthlyDay: Number(dom),
      customCron: cron,
    };
  }
  return { ...fallback, preset: "custom", customCron: cron };
}

function buildCron(s: BuilderState): string {
  switch (s.preset) {
    case "every_n_min":
      return `*/${s.everyN} * * * *`;
    case "hourly":
      return `${s.hourlyMinute} * * * *`;
    case "daily":
      return `${s.dailyMinute} ${s.dailyHour} * * *`;
    case "weekly": {
      const days = s.weeklyDays.length ? s.weeklyDays.sort((a, b) => a - b).join(",") : "*";
      return `${s.dailyMinute} ${s.dailyHour} * * ${days}`;
    }
    case "monthly":
      return `${s.dailyMinute} ${s.dailyHour} ${s.monthlyDay} * *`;
    case "custom":
      return s.customCron;
  }
}

export function CronBuilder({ value, onChange }: CronBuilderProps) {
  const [state, setState] = useState<BuilderState>(() => parseCronIntoState(value, DEFAULTS));

  // Re-sync if the parent hands us a different value (e.g. loaded schedule).
  useEffect(() => {
    setState(parseCronIntoState(value, DEFAULTS));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const cronString = useMemo(() => buildCron(state), [state]);

  // Push the generated cron up to the parent whenever the builder emits
  // something new.
  useEffect(() => {
    if (cronString !== value) {
      onChange(cronString);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cronString]);

  const preview = useQuery({
    queryKey: ["cron-preview", cronString],
    queryFn: () => api.previewCron(cronString),
    enabled: !!cronString,
    staleTime: 30_000,
  });

  const set = <K extends keyof BuilderState>(k: K, v: BuilderState[K]) =>
    setState((prev) => ({ ...prev, [k]: v }));

  return (
    <div className="space-y-3 rounded-md border border-dashed p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label className="text-xs">Preset</Label>
          <Select
            value={state.preset}
            onValueChange={(v) => set("preset", v as Preset)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(PRESET_LABELS).map(([k, label]) => (
                <SelectItem key={k} value={k}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {state.preset === "every_n_min" && (
          <div>
            <Label className="text-xs">Minutes</Label>
            <Select value={String(state.everyN)} onValueChange={(v) => set("everyN", Number(v))}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[1, 2, 5, 10, 15, 20, 30].map((n) => (
                  <SelectItem key={n} value={String(n)}>
                    every {n} {n === 1 ? "minute" : "minutes"}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {state.preset === "hourly" && (
          <div>
            <Label className="text-xs">At minute</Label>
            <Select
              value={String(state.hourlyMinute)}
              onValueChange={(v) => set("hourlyMinute", Number(v))}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Array.from({ length: 60 }, (_, i) => (
                  <SelectItem key={i} value={String(i)}>
                    :{i.toString().padStart(2, "0")}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {(state.preset === "daily" || state.preset === "weekly" || state.preset === "monthly") && (
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Label className="text-xs">Hour</Label>
              <Select
                value={String(state.dailyHour)}
                onValueChange={(v) => set("dailyHour", Number(v))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Array.from({ length: 24 }, (_, h) => (
                    <SelectItem key={h} value={String(h)}>
                      {h.toString().padStart(2, "0")}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1">
              <Label className="text-xs">Minute</Label>
              <Select
                value={String(state.dailyMinute)}
                onValueChange={(v) => set("dailyMinute", Number(v))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Array.from({ length: 60 }, (_, m) => (
                    <SelectItem key={m} value={String(m)}>
                      {m.toString().padStart(2, "0")}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}
      </div>

      {state.preset === "weekly" && (
        <div>
          <Label className="text-xs">Days of week</Label>
          <div className="mt-1 flex flex-wrap gap-1">
            {DOW_LABELS.map((label, idx) => {
              const active = state.weeklyDays.includes(idx);
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() =>
                    set(
                      "weeklyDays",
                      active
                        ? state.weeklyDays.filter((d) => d !== idx)
                        : [...state.weeklyDays, idx]
                    )
                  }
                  className={
                    "rounded-md border px-2 py-1 text-xs transition-colors " +
                    (active
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-input hover:bg-accent")
                  }
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {state.preset === "monthly" && (
        <div>
          <Label className="text-xs">Day of month</Label>
          <Select
            value={String(state.monthlyDay)}
            onValueChange={(v) => set("monthlyDay", Number(v))}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Array.from({ length: 31 }, (_, d) => (
                <SelectItem key={d + 1} value={String(d + 1)}>
                  {d + 1}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {state.preset === "custom" && (
        <div>
          <Label className="text-xs">Cron expression (5 fields)</Label>
          <Input
            value={state.customCron}
            onChange={(e) => set("customCron", e.target.value)}
            className="font-mono"
            placeholder="7 9 * * *"
          />
          <p className="mt-1 text-xs text-muted-foreground">
            Format: <code>minute hour day-of-month month day-of-week</code>
          </p>
        </div>
      )}

      <div className="rounded bg-muted/40 px-3 py-2 text-xs">
        <div className="font-mono">{cronString || "(empty)"}</div>
        {preview.data && preview.data.error && (
          <p className="mt-1 text-destructive">{preview.data.error}</p>
        )}
        {preview.data && !preview.data.error && (
          <p className="mt-1 text-muted-foreground">
            next:{" "}
            {preview.data.next
              .map((ts) =>
                new Date(ts).toLocaleString(undefined, {
                  weekday: "short",
                  month: "short",
                  day: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                })
              )
              .join(" · ") || "never"}
          </p>
        )}
      </div>
    </div>
  );
}
