// Thin fetch wrapper + TanStack Query client.
// Every call uses credentials:"include" so the session cookie is sent
// (same-origin in prod, proxied through Vite in dev).
import { QueryClient } from "@tanstack/react-query";
import type {
  ApplyPaymentsResponse,
  BackfillCreateBody,
  BackfillJob,
  BackfillJobDetail,
  BackfillPlanPreview,
  BillRunResult,
  BillRunStatus,
  CatalogImportPreview,
  CurrentUser,
  DashboardRow,
  OpenInvoice,
  PaymentItem,
  Run,
  RunEvent,
  Schedule,
  Tenant,
  TenantConfig,
  TenantConfigEnvelope,
  WriteOffResult,
} from "./types";

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, err) => {
        // Don't retry auth errors — bounce to login instead.
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          return false;
        }
        return failureCount < 2;
      },
      staleTime: 5_000,
      refetchOnWindowFocus: false,
    },
  },
});

async function req<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...(init.headers || {}),
    },
    ...init,
  });

  if (res.status === 401 || res.status === 403) {
    // Rough-and-ready: bounce to /login. AuthProvider will pick it up.
    if (!path.startsWith("/api/auth/me") && !location.pathname.startsWith("/login")) {
      location.href = "/login";
    }
  }

  // 204 No Content
  if (res.status === 204) return undefined as T;

  const text = await res.text();
  const body = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;

  if (!res.ok) {
    const msg =
      body && typeof body === "object" && "detail" in (body as object)
        ? String((body as { detail: unknown }).detail)
        : `${res.status} ${res.statusText}`;
    throw new ApiError(res.status, body, msg);
  }
  return body as T;
}

// --- Auth ------------------------------------------------------------------

export const api = {
  me: () => req<CurrentUser>("/api/auth/me"),
  devLogin: () =>
    req<CurrentUser>("/api/auth/dev-login", { method: "POST" }),
  logout: () => req<void>("/api/auth/logout", { method: "POST" }),

  // --- Dashboard ---
  dashboard: () => req<DashboardRow[]>("/api/dashboard"),

  // --- Tenants ---
  listTenants: () => req<Tenant[]>("/api/tenants"),
  getTenant: (id: number) => req<Tenant>(`/api/tenants/${id}`),
  createTenant: (body: Omit<Tenant, "id" | "created_at"> & { client_secret: string }) =>
    req<Tenant>("/api/tenants", { method: "POST", body: JSON.stringify(body) }),
  updateTenant: (
    id: number,
    body: Omit<Tenant, "id" | "created_at"> & { client_secret?: string }
  ) => req<Tenant>(`/api/tenants/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteTenant: (id: number) =>
    req<void>(`/api/tenants/${id}`, { method: "DELETE" }),

  // --- Tenant config ---
  getConfig: (tenantId: number) =>
    req<TenantConfigEnvelope>(`/api/tenants/${tenantId}/config`),
  saveConfig: (tenantId: number, config: TenantConfig) =>
    req<TenantConfigEnvelope>(`/api/tenants/${tenantId}/config`, {
      method: "PUT",
      body: JSON.stringify(config),
    }),
  importCatalog: (tenantId: number) =>
    req<CatalogImportPreview>(`/api/tenants/${tenantId}/config/import-preview`, {
      method: "POST",
    }),
  importCurrencies: (tenantId: number) =>
    req<{ currencies: Record<string, string[]> }>(`/api/tenants/${tenantId}/config/import-currencies`, {
      method: "POST",
    }),

  // --- Runs ---
  startRun: (tenantId: number) =>
    req<Run>(`/api/tenants/${tenantId}/runs`, { method: "POST" }),
  getRun: (runId: number) => req<Run>(`/api/runs/${runId}`),
  getRunEvents: (runId: number, sinceSeq = 0) =>
    req<RunEvent[]>(`/api/runs/${runId}/events?since=${sinceSeq}`),
  cancelRun: (runId: number) =>
    req<Run>(`/api/runs/${runId}/cancel`, { method: "POST" }),
  listRuns: (limit = 100) => req<Run[]>(`/api/runs?limit=${limit}`),

  // --- Schedules ---
  listSchedules: (tenantId: number) =>
    req<Schedule[]>(`/api/tenants/${tenantId}/schedules`),
  createSchedule: (tenantId: number, body: { cron: string; label: string; enabled: boolean }) =>
    req<Schedule>(`/api/tenants/${tenantId}/schedules`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateSchedule: (
    tenantId: number,
    sid: number,
    body: { cron: string; label: string }
  ) =>
    req<Schedule>(`/api/tenants/${tenantId}/schedules/${sid}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  toggleSchedule: (tenantId: number, sid: number) =>
    req<Schedule>(`/api/tenants/${tenantId}/schedules/${sid}/toggle`, {
      method: "POST",
    }),
  deleteSchedule: (tenantId: number, sid: number) =>
    req<void>(`/api/tenants/${tenantId}/schedules/${sid}`, { method: "DELETE" }),
  previewCron: (cron: string) =>
    req<{ next: string[]; error: string | null }>(
      `/api/schedules/preview?cron=${encodeURIComponent(cron)}`
    ),

  // --- Backfill jobs ---
  previewBackfill: (tenantId: number, body: BackfillCreateBody) =>
    req<BackfillPlanPreview>(`/api/tenants/${tenantId}/backfills/preview`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  startBackfill: (tenantId: number, body: BackfillCreateBody) =>
    req<BackfillJob>(`/api/tenants/${tenantId}/backfills`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getBackfill: (jobId: number) =>
    req<BackfillJobDetail>(`/api/backfills/${jobId}`),
  cancelBackfill: (jobId: number) =>
    req<BackfillJob>(`/api/backfills/${jobId}/cancel`, { method: "POST" }),
  listBackfills: (tenantId: number) =>
    req<BackfillJob[]>(`/api/tenants/${tenantId}/backfills`),

  // --- Billing & Payments ---
  triggerBillRun: (tenantId: number, targetDate: string, invoiceDate?: string) =>
    req<BillRunResult>(`/api/tenants/${tenantId}/billing/run`, {
      method: "POST",
      body: JSON.stringify({ target_date: targetDate, invoice_date: invoiceDate }),
    }),
  getBillRunStatus: (tenantId: number, billRunId: string) =>
    req<BillRunStatus>(`/api/tenants/${tenantId}/billing/run-status/${billRunId}`),
  getOpenInvoices: (tenantId: number) =>
    req<OpenInvoice[]>(`/api/tenants/${tenantId}/billing/open-invoices`),
  applyPayments: (tenantId: number, payments: PaymentItem[]) =>
    req<ApplyPaymentsResponse>(`/api/tenants/${tenantId}/billing/apply-payments`, {
      method: "POST",
      body: JSON.stringify({ payments }),
    }),
  writeOffInvoice: (tenantId: number, invoiceId: string, amount: number, reasonCode?: string, comment?: string) =>
    req<WriteOffResult>(`/api/tenants/${tenantId}/billing/write-off`, {
      method: "POST",
      body: JSON.stringify({ invoice_id: invoiceId, amount, reason_code: reasonCode, comment }),
    }),
};
