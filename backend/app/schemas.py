"""
Pydantic response/request shapes for the JSON API.

Kept minimal and hand-written so the frontend's TypeScript types in
frontend/src/lib/types.ts can be maintained in lockstep without a code-gen
step. Every new field added here needs a matching entry over there.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth ------------------------------------------------------------------


class CurrentUserOut(_Base):
    id: int
    email: str
    name: str | None = None


# --- Tenants ---------------------------------------------------------------


class TenantOut(_Base):
    id: int
    name: str
    environment: str
    base_url: str
    client_id: str
    created_at: datetime


class TenantCreate(BaseModel):
    name: str
    environment: str
    base_url: str
    client_id: str
    client_secret: str


class TenantUpdate(BaseModel):
    name: str
    environment: str
    base_url: str
    client_id: str
    # Optional — if None/empty, the existing encrypted secret is preserved.
    client_secret: str | None = None


# --- Tenant config ---------------------------------------------------------


class RatePlanModel(BaseModel):
    name: str = ""
    period: str = "Annual"
    product_rate_plan_id: str = ""


class ProductModel(BaseModel):
    label: str = ""
    tier: int = 1
    rate_plans: list[RatePlanModel] = Field(default_factory=list)


class AddonModel(BaseModel):
    name: str = ""
    product_rate_plan_id: str = ""


class MandatorySubModel(BaseModel):
    subscription_number: str = ""
    use_case: str = ""
    notes: str = ""


class NamePoolModel(BaseModel):
    prefixes: list[str] = Field(default_factory=list)
    suffixes: list[str] = Field(default_factory=list)


class TenantConfigBody(BaseModel):
    products: list[ProductModel] = Field(default_factory=list)
    addons: list[AddonModel] = Field(default_factory=list)
    mandatory_subs: list[MandatorySubModel] = Field(default_factory=list)
    new_subs_min: int = 0
    new_subs_max: int = 0
    amendments_min: int = 0
    amendments_max: int = 0
    cancellations_min: int = 0
    cancellations_max: int = 0
    usage_posts_min: int = 0
    usage_posts_max: int = 0
    tier_mix: dict[str, int] = Field(default_factory=dict)
    amendment_mix: dict[str, int] = Field(default_factory=dict)
    growth_bias_bp: int = 100
    name_pool: NamePoolModel = Field(default_factory=NamePoolModel)


class ValidationIssueOut(BaseModel):
    field: str
    severity: Literal["error", "warning"]
    message: str


class TenantConfigEnvelopeOut(BaseModel):
    config: TenantConfigBody
    issues: list[ValidationIssueOut]
    prompt_preview: str


# --- Runs ------------------------------------------------------------------


class RunOut(_Base):
    id: int
    tenant_id: int
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    tool_call_count: int = 0
    cost_usd: float | None = None
    summary_md: str = ""
    error_message: str = ""
    triggered_by_user_id: int | None = None
    backfill_date: datetime | None = None
    parent_job_id: int | None = None


class RunEventOut(_Base):
    id: int
    seq: int
    kind: str
    payload: dict[str, Any]
    created_at: datetime


# --- Dashboard -------------------------------------------------------------


class ScheduleOut(_Base):
    id: int
    tenant_id: int
    cron: str
    label: str = ""
    enabled: bool
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None


class DashboardRowOut(BaseModel):
    tenant: TenantOut
    health: Literal["ok", "warn", "error"]
    errors: list[ValidationIssueOut]
    warnings: list[ValidationIssueOut]
    last_run: "RunOut | None" = None
    next_sched: "ScheduleOut | None" = None
    in_flight_backfill: "BackfillJobOut | None" = None


# --- Schedules -------------------------------------------------------------


class ScheduleCreate(BaseModel):
    cron: str
    label: str = ""
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    cron: str
    label: str = ""


class CronPreviewOut(BaseModel):
    next: list[datetime]
    error: str | None = None


# --- Catalog import --------------------------------------------------------


class ImportedRatePlanOut(BaseModel):
    name: str
    period: str
    product_rate_plan_id: str


class ImportedProductOut(BaseModel):
    label: str
    tier: int
    rate_plans: list[ImportedRatePlanOut]


class ImportedAddonOut(BaseModel):
    name: str
    product_rate_plan_id: str


class CatalogImportPreviewOut(BaseModel):
    products: list[ImportedProductOut]
    addons: list[ImportedAddonOut]
    total_products_seen: int
    total_rate_plans_seen: int
    warnings: list[str]


# --- Backfill jobs ---------------------------------------------------------


class BackfillJobCreate(BaseModel):
    start_date: datetime
    end_date: datetime
    granularity: Literal["monthly"] = "monthly"
    label: str = ""


class BackfillPlanPreviewOut(BaseModel):
    """What the modal shows before the user hits 'Start'."""

    label: str
    batch_count: int
    batch_dates: list[datetime]
    estimated_cost_usd: float | None  # null if we don't have priors


class BackfillJobOut(_Base):
    id: int
    tenant_id: int
    triggered_by_user_id: int | None = None
    label: str = ""
    start_date: datetime
    end_date: datetime
    granularity: str
    status: str
    total_batches: int
    completed_batches: int
    error_message: str = ""
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class BackfillJobDetailOut(BackfillJobOut):
    """Job + child runs + aggregate cost."""

    child_runs: list[RunOut]
    total_cost_usd: float | None = None
