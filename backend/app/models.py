"""
SQLAlchemy models.

Phase 1: User, Tenant.
Phase 2: Run, RunEvent.
Phase 3 will add: Schedule.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    picture_url: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    tenants: Mapped[list["Tenant"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Tenant(Base):
    """
    A Zuora tenant a user has registered. The client_secret is encrypted at
    rest with a Fernet key from settings.MASTER_ENCRYPTION_KEY. Everything
    else is plaintext because it's fine to see in the UI / DB.
    """

    __tablename__ = "tenants"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tenant_name_per_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # Human-facing nickname, e.g. "CSBX – My Sandbox".
    name: Mapped[str] = mapped_column(String(255))

    # Machine-facing metadata.
    environment: Mapped[str] = mapped_column(String(32))  # CSBX, SBX, PROD, etc.
    base_url: Mapped[str] = mapped_column(String(255))    # https://rest.test.zuora.com

    client_id: Mapped[str] = mapped_column(String(128))
    # Fernet-encrypted ciphertext string. Decrypt via app.crypto.decrypt().
    client_secret_encrypted: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    owner: Mapped[User] = relationship(back_populates="tenants")
    runs: Mapped[list["Run"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    config: Mapped["TenantConfig | None"] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        uselist=False,
    )
    schedules: Mapped[list["Schedule"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


# --- Tenant config --------------------------------------------------------


class TenantConfig(Base):
    """
    Per-tenant configuration for what data the skill should generate.

    Shape-free JSON for the variable-length collections (products, addons,
    mandatory subs, name pool) and plain columns for the scalar dials.
    A fresh row is auto-created alongside each Tenant with defaults drawn
    from the values that were hardcoded into SKILL.md.

    JSON schemas (validated structurally in app.tenant_config):

    products = [
      {
        "label": "Basic",
        "tier": 1,
        "rate_plans": [
          {"name": "Month to Month", "period": "MTM", "product_rate_plan_id": "..."},
          {"name": "Annual Plan", "period": "Annual", "product_rate_plan_id": "..."},
        ],
      },
      ...
    ]

    addons = [
      {"name": "CloudStream Analytics Annual", "product_rate_plan_id": "..."},
      ...
    ]

    mandatory_subs = [
      {"subscription_number": "A-S00000354", "use_case": "Min Commit", "notes": "..."},
      ...
    ]

    name_pool = {
      "prefixes": ["Apex", "NovaBridge", ...],
      "suffixes": ["Technologies", "Software", ...],
    }
    """

    __tablename__ = "tenant_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, index=True
    )

    # --- catalog + subs ---
    products: Mapped[list] = mapped_column(JSON, default=list)
    addons: Mapped[list] = mapped_column(JSON, default=list)
    mandatory_subs: Mapped[list] = mapped_column(JSON, default=list)

    # --- volume ranges ---
    new_subs_min: Mapped[int] = mapped_column(Integer, default=8)
    new_subs_max: Mapped[int] = mapped_column(Integer, default=15)
    amendments_min: Mapped[int] = mapped_column(Integer, default=6)
    amendments_max: Mapped[int] = mapped_column(Integer, default=12)
    cancellations_min: Mapped[int] = mapped_column(Integer, default=2)
    cancellations_max: Mapped[int] = mapped_column(Integer, default=4)
    usage_posts_min: Mapped[int] = mapped_column(Integer, default=5)
    usage_posts_max: Mapped[int] = mapped_column(Integer, default=10)

    # --- ratios (0–100 integers, must sum to 100 within each group) ---
    tier_mix: Mapped[dict] = mapped_column(JSON, default=dict)
    # Example: {"1": 50, "2": 35, "3": 15}
    amendment_mix: Mapped[dict] = mapped_column(JSON, default=dict)
    # Example: {"upgrade": 45, "add_product": 30, "downgrade": 10, "remove_product": 15}

    # --- growth bias ---
    # Multiplier on "growth" picks (new + upgrade + add-product).
    # 1.0 = neutral. Stored *100 as an int so SQLite + forms stay simple.
    growth_bias_bp: Mapped[int] = mapped_column(Integer, default=100)  # 100 = 1.0x

    # --- account type + name pool ---
    # "company" (B2B) → company names from name_pool.prefixes + .suffixes
    # ("Apex Technologies"). "person" (B2C) → person names from
    # name_pool.first_names + .last_names ("John Smith"). "mixed" → a blend of
    # both, where company_share is the % of new accounts that are companies.
    account_type: Mapped[str] = mapped_column(String, default="company")
    company_share: Mapped[int] = mapped_column(Integer, default=50)  # only used when mixed
    name_pool: Mapped[dict] = mapped_column(JSON, default=dict)

    # --- currency mix ---
    currency_mix: Mapped[dict] = mapped_column(JSON, default=dict)
    # Example: {"USD": 60, "EUR": 25, "GBP": 15} — percentages must sum to 100

    # --- payments & write-offs ---
    payments: Mapped[dict] = mapped_column(JSON, default=dict)
    # Example: {"enabled": true, "pay_percentage_min": 60, "pay_percentage_max": 80, "payment_lag_days_min": 1, "payment_lag_days_max": 5}
    writeoffs: Mapped[dict] = mapped_column(JSON, default=dict)
    # Example: {"enabled": true, "frequency": "every_other_run", "count_min": 1, "count_max": 2, "max_invoice_amount": 500}

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    tenant: Mapped[Tenant] = relationship(back_populates="config")

    @property
    def growth_bias(self) -> float:
        return (self.growth_bias_bp or 0) / 100.0


# --- Schedules ------------------------------------------------------------


class Schedule(Base):
    """
    A cron-style recurring schedule for a tenant.

    APScheduler holds the *live* job object in memory and is the one that
    actually fires on time; this table is the durable source of truth that
    the scheduler module syncs from on startup and on every CRUD call.

    `last_run_at` is informational only — updated when a fire succeeds in
    creating a Run row. `next_run_at` is recomputed from the cron
    expression any time the schedule is saved and on each fire, so the
    dashboard can show a friendly countdown without asking APScheduler.
    """

    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )

    # Human-entered 5-field cron expression. Validated on save via
    # CronTrigger.from_crontab(). We keep the raw string so the editor
    # round-trips exactly what the user typed.
    cron: Mapped[str] = mapped_column(String(128))

    # Optional label so users can distinguish "nightly" from "hourly demo".
    label: Mapped[str] = mapped_column(String(120), default="")

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    tenant: Mapped[Tenant] = relationship(back_populates="schedules")


# --- Backfill jobs --------------------------------------------------------


class BackfillJob(Base):
    """
    A one-shot historical data population job for a tenant.

    The coordinator splits the requested date range into N monthly batches
    and creates one child Run per batch, firing them serially. Each child
    Run.backfill_date is the calendar date that batch pretends is "today".

    Status transitions:
      queued  -> running -> (succeeded | failed | cancelled)

    On first child-run failure the coordinator marks the job failed and
    stops — we don't silently keep going, because a failed batch usually
    means a config/creds problem that will affect every subsequent batch.

    Concurrency: while a BackfillJob is in queued/running state for a
    tenant, manual runs and scheduled fires for that tenant are blocked.
    The enforcement happens in runner.find_in_flight_run and in the
    scheduler's _fire_scheduled_run.
    """

    __tablename__ = "backfill_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Human-friendly label shown on the job page. Auto-generated at create
    # time ("Backfill 2025-04 → 2026-04") but user can override via the
    # modal in the future if we want.
    label: Mapped[str] = mapped_column(String(200), default="")

    # Closed date range, inclusive on start, exclusive on end. Stored as
    # timezone-aware timestamps so we can do arithmetic without tz bugs.
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # "monthly" for now. Phase 7 can add weekly/daily if the user asks.
    granularity: Mapped[str] = mapped_column(String(16), default="monthly")

    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    total_batches: Mapped[int] = mapped_column(Integer, default=0)
    completed_batches: Mapped[int] = mapped_column(Integer, default=0)

    error_message: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped[Tenant] = relationship()
    child_runs: Mapped[list[Run]] = relationship(
        back_populates="parent_job",
        foreign_keys="Run.parent_job_id",
        order_by="Run.id",
    )


# --- Runs -----------------------------------------------------------------


class Run(Base):
    """
    A single execution of the skill against a tenant. Status transitions:
      queued -> running -> (succeeded | failed | cancelled)
    """

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    # Who clicked "Run now" — used later for read-only team visibility.
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    trigger: Mapped[str] = mapped_column(String(16), default="manual")  # manual | schedule
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    # "queued" | "running" | "succeeded" | "failed" | "cancelled"

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Populated at completion time.
    summary_md: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(Text, default="")

    # Coarse counters — displayed on the dashboard so we don't have to scan RunEvents.
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)

    # Total USD cost reported by the Claude Agent SDK's ResultMessage.
    # Null until the run completes (or for failed runs that never ran a model).
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Backfill fields (Phase 6). When set, the runner treats this as a
    # "pretend today is YYYY-MM-DD" historical batch:
    #   - backfill_date: the effective date the skill should use for every
    #     Zuora operation in this batch. Null for normal runs.
    #   - parent_job_id: the BackfillJob that spawned this run, if any.
    backfill_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    parent_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("backfill_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    tenant: Mapped[Tenant] = relationship(back_populates="runs")
    parent_job: Mapped["BackfillJob | None"] = relationship(
        back_populates="child_runs", foreign_keys=[parent_job_id]
    )
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunEvent.seq",
    )


class RunEvent(Base):
    """
    A single streaming event from the Claude Agent SDK: a tool_use, an
    assistant text block, or a terminal result. The UI polls/streams these
    in order (by seq) to render the live feed.
    """

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)  # monotonic within a run
    kind: Mapped[str] = mapped_column(String(32))  # tool_use | text | result | error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Shape varies by kind — see runner._event_payload for the keys. Stored
    # as JSON so we don't have to schema-design every variant upfront.
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped[Run] = relationship(back_populates="events")
