import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function formatUsd(cost: number | null | undefined): string {
  if (cost == null) return "—";
  return `$${cost.toFixed(4)}`;
}

export function formatCurrency(amount: number | null | undefined): string {
  if (amount == null) return "—";
  return `$${amount.toFixed(2)}`;
}
