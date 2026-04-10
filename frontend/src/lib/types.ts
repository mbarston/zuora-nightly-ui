// Hand-written mirrors of the backend's JSON shapes. Kept in sync with
// backend/app/schemas.py. Any drift will show up as a 422 from the API
// or a runtime render error — tolerable for an internal tool where the
// same person owns both sides.

export interface CurrentUser {
  id: number;
  email: string;
  name: string | null;
}

export interface Tenant {
  id: number;
  name: string;
  environment: string;
  base_url: string;
  client_id: string;
  created_at: string;
}

export interface RatePlan {
  name: string;
  period: string; // "MTM" | "Annual" | "Other"
  product_rate_plan_id: string;
}

export interface Product {
  label: string;
  tier: number;
  rate_plans: RatePlan[];
}

export interface Addon {
  name: string;
  product_rate_plan_id: string;
}

export interface MandatorySub {
  subscription_number: string;
  use_case: string;
  notes: string;
}

export interface NamePool {
  prefixes: string[];
  suffixes: string[];
}

export interface TenantConfig {
  products: Product[];
  addons: Addon[];
  mandatory_subs: MandatorySub[];
  new_subs_min: number;
  new_subs_max: number;
  amendments_min: number;
  amendments_max: number;
  cancellations_min: number;
  cancellations_max: number;
  usage_posts_min: number;
  usage_posts_max: number;
  tier_mix: Record<string, number>;
  amendment_mix: Record<string, number>;
  growth_bias_bp: number;
  name_pool: NamePool;
  payments: {
    enabled: boolean;
    pay_percentage_min: number;
    pay_percentage_max: number;
    payment_lag_days_min: number;
    payment_lag_days_max: number;
  };
  writeoffs: {
    enabled: boolean;
    frequency: string;
    count_min: number;
    count_max: number;
    max_invoice_amount: number;
  };
}

export interface ValidationIssue {
  field: string;
  severity: "error" | "warning";
  message: string;
}

export interface TenantConfigEnvelope {
  config: TenantConfig;
  issues: ValidationIssue[];
  prompt_preview: string;
}

export interface Schedule {
  id: number;
  tenant_id: number;
  cron: string;
  label: string;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
}

export interface SchedulePreviews {
  next: string[];
}

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type RunTrigger = "manual" | "schedule" | "backfill";

export interface Run {
  id: number;
  tenant_id: number;
  trigger: RunTrigger;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  tool_call_count: number;
  cost_usd: number | null;
  summary_md: string;
  error_message: string;
  triggered_by_user_id: number | null;
  backfill_date: string | null;
  parent_job_id: number | null;
}

export interface RunEvent {
  id: number;
  seq: number;
  kind: string; // "tool_use" | "text" | "result" | "system" | "error" | ...
  payload: Record<string, unknown>;
  created_at: string;
}

export interface DashboardRow {
  tenant: Tenant;
  health: "ok" | "warn" | "error";
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  last_run: Run | null;
  next_sched: Schedule | null;
  in_flight_backfill: BackfillJob | null;
}

export interface ImportedRatePlan {
  name: string;
  period: string;
  product_rate_plan_id: string;
}

export interface ImportedProduct {
  label: string;
  tier: number;
  rate_plans: ImportedRatePlan[];
}

export interface ImportedAddon {
  name: string;
  product_rate_plan_id: string;
}

export interface CatalogImportPreview {
  products: ImportedProduct[];
  addons: ImportedAddon[];
  total_products_seen: number;
  total_rate_plans_seen: number;
  warnings: string[];
}

// --- Backfill jobs --------------------------------------------------------

export type BackfillStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface BackfillJob {
  id: number;
  tenant_id: number;
  triggered_by_user_id: number | null;
  label: string;
  start_date: string;
  end_date: string;
  granularity: "monthly";
  status: BackfillStatus;
  total_batches: number;
  completed_batches: number;
  error_message: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface BackfillJobDetail extends BackfillJob {
  child_runs: Run[];
  total_cost_usd: number | null;
}

export interface BackfillPlanPreview {
  label: string;
  batch_count: number;
  batch_dates: string[];
  estimated_cost_usd: number | null;
}

export interface BackfillCreateBody {
  start_date: string;
  end_date: string;
  granularity: "monthly";
  label: string;
}

// --- Billing & Payments ---------------------------------------------------

export interface BillRunResult {
  id: string;
  status: string;
}

export interface BillRunStatus {
  id: string;
  status: string;
  invoices_generated: number;
  credit_memos_generated: number;
  errors: number;
  created_date: string | null;
}

export interface OpenInvoice {
  id: string;
  invoice_number: string;
  invoice_date: string;
  amount: number;
  balance: number;
  account_id: string;
  account_name: string;
  currency: string;
  due_date: string;
  age_days: number;
}

export interface PaymentItem {
  invoice_id: string;
  account_id: string;
  amount: number;
  effective_date: string;
  currency: string;
}

export interface PaymentResult {
  success: boolean;
  payment_id: string;
  payment_number: string;
  amount: number;
  status: string;
}

export interface ApplyPaymentsResponse {
  results: PaymentResult[];
  errors: Array<{ invoice_id: string; error: string }>;
}

export interface WriteOffResult {
  success: boolean;
  credit_memo_id: string;
  credit_memo_number: string;
  amount: number;
  applied: boolean;
}
