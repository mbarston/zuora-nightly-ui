import * as React from "react";
import { cn } from "@/lib/utils";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?:
    | "default"
    | "queued"
    | "running"
    | "succeeded"
    | "failed"
    | "cancelled"
    | "ok"
    | "warn"
    | "error"
    | "manual"
    | "schedule"
    | "backfill";
}

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  const variantClass =
    variant === "default"
      ? "bg-muted text-muted-foreground"
      : variant === "manual"
      ? "bg-blue-500/20 text-blue-400"
      : variant === "schedule"
      ? "bg-purple-500/20 text-purple-400"
      : variant === "backfill"
      ? "bg-cyan-500/20 text-cyan-400"
      : `badge-${variant}`;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[0.7rem] font-semibold uppercase tracking-wide",
        variantClass,
        className
      )}
      {...props}
    />
  );
}
