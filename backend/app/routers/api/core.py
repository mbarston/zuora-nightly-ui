"""
JSON API routes under /api/*.

Mirrors the existing HTML routes but returns JSON everywhere. The React
frontend is the only consumer — the Jinja routes are kept alive in parallel
during Phase 5a/5b and are removed in Phase 5c.

Authentication model:
  - /api/auth/* handles login/logout/whoami and returns 401 when no session.
  - All other /api/* routes require a session. When missing, return 401
    (NOT redirect — the React app handles the bounce to /login on its own).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from pydantic import BaseModel as PydanticBaseModel
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from pathlib import Path

from app.backfill import (
    compute_batch_dates,
    default_label,
    find_in_flight_backfill,
    start_backfill_in_background,
)
from app.catalog_import import CatalogImportError
from app.catalog_import import import_catalog as run_catalog_import
from app.config import settings
from app.crypto import decrypt, encrypt
from app.db import SessionLocal, get_db
from app.models import BackfillJob, Run, RunEvent, Schedule, Tenant, TenantConfig, User
from app.runner import find_concurrency_blocker, find_in_flight_run, start_run_in_background
from app.scheduler import (
    CronParseError,
    next_fire_time,
    next_fire_times,
    parse_cron,
    remove_schedule as scheduler_remove,
    sync_schedule,
)
from app.schemas import (
    BackfillJobCreate,
    BackfillJobDetailOut,
    BackfillJobOut,
    BackfillPlanPreviewOut,
    CatalogImportPreviewOut,
    CronPreviewOut,
    CurrentUserOut,
    DashboardRowOut,
    RunEventOut,
    RunOut,
    ScheduleCreate,
    ScheduleOut,
    ScheduleUpdate,
    TenantConfigBody,
    TenantConfigEnvelopeOut,
    TenantCreate,
    TenantOut,
    TenantUpdate,
    ValidationIssueOut,
)
from app.tenant_config import seed_default_config, to_prompt_markdown, validate


router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Auth dependency — returns JSON 401 instead of redirecting
# ---------------------------------------------------------------------------


def require_api_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.get(User, user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session user disappeared")
    return user


# ---------------------------------------------------------------------------
# /api/auth
# ---------------------------------------------------------------------------


@router.get("/auth/me", response_model=CurrentUserOut)
def auth_me(user: User = Depends(require_api_user)):
    return user


@router.post("/auth/dev-login", response_model=CurrentUserOut)
def auth_dev_login(request: Request, db: Session = Depends(get_db)):
    if not settings.DEV_AUTH_BYPASS:
        raise HTTPException(status_code=403, detail="Dev bypass disabled")
    # Find or create the dev user.
    user = db.query(User).filter(User.email == "dev@localhost").one_or_none()
    if user is None:
        user = User(
            email="dev@localhost",
            name="Dev",
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
    request.session["user_id"] = user.id
    return user


@router.post("/auth/logout")
def auth_logout(request: Request):
    request.session.clear()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _owned_tenant(db: Session, user: User, tenant_id: int) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.user_id != user.id:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def _get_or_seed_config(db: Session, tenant: Tenant) -> TenantConfig:
    cfg = (
        db.query(TenantConfig).filter(TenantConfig.tenant_id == tenant.id).one_or_none()
    )
    if cfg is None:
        cfg = seed_default_config(tenant.id)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def _envelope(tenant: Tenant, cfg: TenantConfig) -> TenantConfigEnvelopeOut:
    issues = validate(cfg)
    return TenantConfigEnvelopeOut(
        config=TenantConfigBody.model_validate(
            {
                "products": cfg.products or [],
                "addons": cfg.addons or [],
                "mandatory_subs": cfg.mandatory_subs or [],
                "new_subs_min": cfg.new_subs_min,
                "new_subs_max": cfg.new_subs_max,
                "amendments_min": cfg.amendments_min,
                "amendments_max": cfg.amendments_max,
                "cancellations_min": cfg.cancellations_min,
                "cancellations_max": cfg.cancellations_max,
                "usage_posts_min": cfg.usage_posts_min,
                "usage_posts_max": cfg.usage_posts_max,
                "tier_mix": cfg.tier_mix or {},
                "amendment_mix": cfg.amendment_mix or {},
                "growth_bias_bp": cfg.growth_bias_bp,
                "name_pool": cfg.name_pool or {"prefixes": [], "suffixes": []},
                "currency_mix": cfg.currency_mix or {},
                "payments": cfg.payments or {},
                "writeoffs": cfg.writeoffs or {},
            }
        ),
        issues=[
            ValidationIssueOut(field=i.field, severity=i.severity, message=i.message)
            for i in issues
        ],
        prompt_preview=to_prompt_markdown(tenant.name, cfg),
    )


# ---------------------------------------------------------------------------
# /api/dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_model=list[DashboardRowOut])
def dashboard(db: Session = Depends(get_db), user: User = Depends(require_api_user)):
    tenants = (
        db.query(Tenant)
        .filter(Tenant.user_id == user.id)
        .order_by(desc(Tenant.created_at))
        .all()
    )
    rows: list[DashboardRowOut] = []
    for t in tenants:
        cfg = (
            db.query(TenantConfig).filter(TenantConfig.tenant_id == t.id).one_or_none()
        )
        issues = validate(cfg)
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        health = "error" if errors else ("warn" if warnings else "ok")
        last_run = (
            db.query(Run)
            .filter(Run.tenant_id == t.id)
            .order_by(desc(Run.id))
            .first()
        )
        next_sched = (
            db.query(Schedule)
            .filter(
                Schedule.tenant_id == t.id,
                Schedule.enabled.is_(True),
                Schedule.next_run_at.is_not(None),
            )
            .order_by(Schedule.next_run_at.asc())
            .first()
        )
        active_backfill = find_in_flight_backfill(db, t.id)
        rows.append(
            DashboardRowOut(
                tenant=TenantOut.model_validate(t),
                health=health,
                errors=[
                    ValidationIssueOut(field=i.field, severity=i.severity, message=i.message)
                    for i in errors
                ],
                warnings=[
                    ValidationIssueOut(field=i.field, severity=i.severity, message=i.message)
                    for i in warnings
                ],
                last_run=RunOut.model_validate(last_run) if last_run else None,
                next_sched=ScheduleOut.model_validate(next_sched) if next_sched else None,
                in_flight_backfill=(
                    BackfillJobOut.model_validate(active_backfill) if active_backfill else None
                ),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# /api/tenants
# ---------------------------------------------------------------------------


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(db: Session = Depends(get_db), user: User = Depends(require_api_user)):
    return (
        db.query(Tenant)
        .filter(Tenant.user_id == user.id)
        .order_by(desc(Tenant.created_at))
        .all()
    )


@router.get("/tenants/{tenant_id}", response_model=TenantOut)
def get_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    return _owned_tenant(db, user, tenant_id)


@router.post("/tenants", response_model=TenantOut)
def create_tenant(
    body: TenantCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    tenant = Tenant(
        user_id=user.id,
        name=body.name.strip(),
        environment=body.environment.strip().upper(),
        base_url=body.base_url.strip(),
        client_id=body.client_id.strip(),
        client_secret_encrypted=encrypt(body.client_secret),
    )
    db.add(tenant)
    db.flush()
    db.add(seed_default_config(tenant.id))
    db.commit()
    db.refresh(tenant)
    return tenant


@router.put("/tenants/{tenant_id}", response_model=TenantOut)
def update_tenant(
    tenant_id: int,
    body: TenantUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    tenant = _owned_tenant(db, user, tenant_id)
    tenant.name = body.name.strip()
    tenant.environment = body.environment.strip().upper()
    tenant.base_url = body.base_url.strip()
    tenant.client_id = body.client_id.strip()
    if body.client_secret:
        tenant.client_secret_encrypted = encrypt(body.client_secret)
    db.commit()
    db.refresh(tenant)
    return tenant


@router.delete("/tenants/{tenant_id}", status_code=204)
def delete_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    tenant = _owned_tenant(db, user, tenant_id)
    db.delete(tenant)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# /api/tenants/{id}/config
# ---------------------------------------------------------------------------


@router.get("/tenants/{tenant_id}/config", response_model=TenantConfigEnvelopeOut)
def get_config(
    tenant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    tenant = _owned_tenant(db, user, tenant_id)
    cfg = _get_or_seed_config(db, tenant)
    return _envelope(tenant, cfg)


@router.put("/tenants/{tenant_id}/config", response_model=TenantConfigEnvelopeOut)
def save_config(
    tenant_id: int,
    body: TenantConfigBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    tenant = _owned_tenant(db, user, tenant_id)
    cfg = _get_or_seed_config(db, tenant)
    cfg.products = [p.model_dump() for p in body.products]
    cfg.addons = [a.model_dump() for a in body.addons]
    cfg.mandatory_subs = [m.model_dump() for m in body.mandatory_subs]
    cfg.new_subs_min = body.new_subs_min
    cfg.new_subs_max = body.new_subs_max
    cfg.amendments_min = body.amendments_min
    cfg.amendments_max = body.amendments_max
    cfg.cancellations_min = body.cancellations_min
    cfg.cancellations_max = body.cancellations_max
    cfg.usage_posts_min = body.usage_posts_min
    cfg.usage_posts_max = body.usage_posts_max
    cfg.tier_mix = {str(k): int(v) for k, v in body.tier_mix.items()}
    cfg.amendment_mix = {str(k): int(v) for k, v in body.amendment_mix.items()}
    cfg.growth_bias_bp = body.growth_bias_bp
    cfg.name_pool = body.name_pool.model_dump()
    cfg.currency_mix = {str(k): int(v) for k, v in body.currency_mix.items()}
    cfg.payments = body.payments
    cfg.writeoffs = body.writeoffs
    db.commit()
    db.refresh(cfg)
    return _envelope(tenant, cfg)


@router.post(
    "/tenants/{tenant_id}/config/import-preview",
    response_model=CatalogImportPreviewOut,
)
async def import_preview(
    tenant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """
    Run the catalog import against the tenant's live Zuora and return the
    preview WITHOUT modifying config. The React app shows a checkbox picker
    and calls PUT /config with the merged selection.
    """
    tenant = _owned_tenant(db, user, tenant_id)
    try:
        client_secret = decrypt(tenant.client_secret_encrypted)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Decrypt failed: {e}") from e
    try:
        preview = await run_catalog_import(
            base_url=tenant.base_url,
            client_id=tenant.client_id,
            client_secret=client_secret,
        )
    except CatalogImportError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return preview.to_dict()


# ---------------------------------------------------------------------------
# /api/runs + /api/tenants/{id}/runs
# ---------------------------------------------------------------------------


@router.post("/tenants/{tenant_id}/runs", response_model=RunOut)
async def start_run(
    tenant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    tenant = _owned_tenant(db, user, tenant_id)

    # Per-tenant concurrency: if a plain run is in flight, redirect to it.
    # If a backfill is in flight, refuse with a 409 — redirecting to a
    # backfill child run's detail page would be confusing.
    in_flight = find_in_flight_run(db, tenant.id)
    if in_flight is not None:
        return in_flight
    backfill = find_in_flight_backfill(db, tenant.id)
    if backfill is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Backfill #{backfill.id} is still running on this tenant "
                f"({backfill.completed_batches}/{backfill.total_batches} batches). "
                "Wait for it to finish before starting a manual run."
            ),
        )

    run = Run(
        tenant_id=tenant.id,
        triggered_by_user_id=user.id,
        trigger="manual",
        status="queued",
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    start_run_in_background(run.id)
    return run


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    return db.query(Run).order_by(desc(Run.id)).limit(limit).all()


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/events", response_model=list[RunEventOut])
def get_run_events(
    run_id: int,
    since: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id, RunEvent.seq > since)
        .order_by(RunEvent.seq)
        .all()
    )


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
async def stop_run(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Cancel an in-flight run by killing its asyncio task."""
    from app.runner import cancel_run

    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in ("queued", "running"):
        raise HTTPException(status_code=400, detail=f"Run is already {run.status}")

    cancelled = cancel_run(run_id)
    if not cancelled:
        # Task already gone — mark it cancelled in the DB directly.
        run.status = "cancelled"
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = "Run cancelled by user."
        db.commit()
    # Give the task a moment to finalize in the DB before we re-read.
    import asyncio
    await asyncio.sleep(0.3)
    db.refresh(run)
    return run


@router.get("/runs/{run_id}/stream")
async def run_stream(
    run_id: int,
    request: Request,
):
    """
    Same SSE stream the Jinja detail page uses, duplicated under /api/ so
    the Vite dev-server proxy targets it correctly. The auth check is
    session-based (not via Depends) because EventSource can't follow
    redirects or attach headers.
    """
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401)

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404)

    async def gen():
        last_seq = 0
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected():
                return
            with SessionLocal() as db:
                run = db.get(Run, run_id)
                if run is None:
                    yield _sse("error", {"message": "run disappeared"})
                    return
                new_events = (
                    db.query(RunEvent)
                    .filter(RunEvent.run_id == run_id, RunEvent.seq > last_seq)
                    .order_by(RunEvent.seq)
                    .all()
                )
                for ev in new_events:
                    yield _sse(
                        "event",
                        {
                            "seq": ev.seq,
                            "kind": ev.kind,
                            "payload": ev.payload,
                            "created_at": ev.created_at.isoformat(),
                        },
                    )
                    last_seq = ev.seq
                if run.status in ("succeeded", "failed", "cancelled"):
                    yield _sse(
                        "done",
                        {
                            "status": run.status,
                            "summary_md": run.summary_md,
                            "error_message": run.error_message,
                            "tool_call_count": run.tool_call_count,
                            "cost_usd": run.cost_usd,
                            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                        },
                    )
                    return
            await asyncio.sleep(0.8)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# ---------------------------------------------------------------------------
# /api/tenants/{id}/schedules + /api/schedules/preview
# ---------------------------------------------------------------------------


@router.get("/tenants/{tenant_id}/schedules", response_model=list[ScheduleOut])
def list_schedules(
    tenant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    _owned_tenant(db, user, tenant_id)
    return (
        db.query(Schedule)
        .filter(Schedule.tenant_id == tenant_id)
        .order_by(Schedule.id.asc())
        .all()
    )


@router.post("/tenants/{tenant_id}/schedules", response_model=ScheduleOut)
def create_schedule(
    tenant_id: int,
    body: ScheduleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    _owned_tenant(db, user, tenant_id)
    try:
        parse_cron(body.cron)
    except CronParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    sched = Schedule(
        tenant_id=tenant_id,
        cron=body.cron.strip(),
        label=body.label.strip(),
        enabled=body.enabled,
        next_run_at=next_fire_time(body.cron.strip()) if body.enabled else None,
    )
    db.add(sched)
    db.commit()
    db.refresh(sched)
    if sched.enabled:
        sync_schedule(sched.id)
    return sched


@router.put("/tenants/{tenant_id}/schedules/{sid}", response_model=ScheduleOut)
def update_schedule(
    tenant_id: int,
    sid: int,
    body: ScheduleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    _owned_tenant(db, user, tenant_id)
    sched = db.get(Schedule, sid)
    if sched is None or sched.tenant_id != tenant_id:
        raise HTTPException(status_code=404)
    try:
        parse_cron(body.cron)
    except CronParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    sched.cron = body.cron.strip()
    sched.label = body.label.strip()
    if sched.enabled:
        sched.next_run_at = next_fire_time(sched.cron)
    db.commit()
    sync_schedule(sched.id)
    db.refresh(sched)
    return sched


@router.post("/tenants/{tenant_id}/schedules/{sid}/toggle", response_model=ScheduleOut)
def toggle_schedule(
    tenant_id: int,
    sid: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    _owned_tenant(db, user, tenant_id)
    sched = db.get(Schedule, sid)
    if sched is None or sched.tenant_id != tenant_id:
        raise HTTPException(status_code=404)
    sched.enabled = not sched.enabled
    sched.next_run_at = next_fire_time(sched.cron) if sched.enabled else None
    db.commit()
    sync_schedule(sched.id)
    db.refresh(sched)
    return sched


@router.delete("/tenants/{tenant_id}/schedules/{sid}", status_code=204)
def delete_schedule(
    tenant_id: int,
    sid: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    _owned_tenant(db, user, tenant_id)
    sched = db.get(Schedule, sid)
    if sched is None or sched.tenant_id != tenant_id:
        raise HTTPException(status_code=404)
    db.delete(sched)
    db.commit()
    scheduler_remove(sid)
    return None


@router.get("/schedules/preview", response_model=CronPreviewOut)
def preview_cron(
    cron: str = Query(...),
    _user: User = Depends(require_api_user),
):
    try:
        times = next_fire_times(cron, count=3)
    except CronParseError as e:
        return CronPreviewOut(next=[], error=str(e))
    return CronPreviewOut(next=times, error=None)


# ---------------------------------------------------------------------------
# /api/tenants/{id}/backfills + /api/backfills/{id}
# ---------------------------------------------------------------------------


def _estimate_backfill_cost(db: Session, tenant_id: int, batch_count: int) -> float | None:
    """
    Rough cost estimate for a backfill, based on the mean cost of the
    last 5 successful runs for this tenant. Returns None if we don't
    have enough history to guess — the UI then just hides the estimate.
    """
    runs = (
        db.query(Run)
        .filter(
            Run.tenant_id == tenant_id,
            Run.status == "succeeded",
            Run.cost_usd.is_not(None),
        )
        .order_by(Run.id.desc())
        .limit(5)
        .all()
    )
    costs = [r.cost_usd for r in runs if r.cost_usd is not None]
    if not costs:
        return None
    mean = sum(costs) / len(costs)
    return round(mean * batch_count, 4)


@router.post(
    "/tenants/{tenant_id}/backfills/preview",
    response_model=BackfillPlanPreviewOut,
)
def preview_backfill_plan(
    tenant_id: int,
    body: BackfillJobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    _owned_tenant(db, user, tenant_id)
    try:
        batches = compute_batch_dates(body.start_date, body.end_date, body.granularity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not batches:
        raise HTTPException(
            status_code=400,
            detail="Date range produced zero batches. Pick at least one full month.",
        )
    return BackfillPlanPreviewOut(
        label=body.label.strip() or default_label(body.start_date, body.end_date),
        batch_count=len(batches),
        batch_dates=batches,
        estimated_cost_usd=_estimate_backfill_cost(db, tenant_id, len(batches)),
    )


@router.post(
    "/tenants/{tenant_id}/backfills",
    response_model=BackfillJobOut,
)
async def start_backfill(
    tenant_id: int,
    body: BackfillJobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    tenant = _owned_tenant(db, user, tenant_id)

    # Refuse if anything is in flight on this tenant (manual, scheduled, or
    # another backfill). Clearer UX than silently queuing behind it.
    blocker = find_concurrency_blocker(db, tenant.id)
    if blocker is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot start backfill: {blocker}. Wait for it to finish.",
        )

    try:
        batches = compute_batch_dates(body.start_date, body.end_date, body.granularity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not batches:
        raise HTTPException(
            status_code=400,
            detail="Date range produced zero batches.",
        )

    job = BackfillJob(
        tenant_id=tenant.id,
        triggered_by_user_id=user.id,
        label=body.label.strip() or default_label(body.start_date, body.end_date),
        start_date=body.start_date,
        end_date=body.end_date,
        granularity=body.granularity,
        status="queued",
        total_batches=len(batches),
        completed_batches=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    start_backfill_in_background(job.id)
    return job


@router.get("/backfills/{job_id}", response_model=BackfillJobDetailOut)
def get_backfill(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    job = db.get(BackfillJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Backfill job not found")
    # Ownership: backfill jobs belong to the tenant owner.
    tenant = db.get(Tenant, job.tenant_id)
    if tenant is None or tenant.user_id != user.id:
        raise HTTPException(status_code=404, detail="Backfill job not found")

    children = (
        db.query(Run)
        .filter(Run.parent_job_id == job_id)
        .order_by(Run.id.asc())
        .all()
    )
    total_cost = sum(
        (r.cost_usd or 0.0) for r in children if r.cost_usd is not None
    )
    any_cost = any(r.cost_usd is not None for r in children)

    return BackfillJobDetailOut(
        **BackfillJobOut.model_validate(job).model_dump(),
        child_runs=[RunOut.model_validate(r) for r in children],
        total_cost_usd=round(total_cost, 4) if any_cost else None,
    )


@router.post("/backfills/{job_id}/cancel", response_model=BackfillJobOut)
def cancel_backfill(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """
    Mark an in-flight backfill as cancelled. The coordinator checks this
    between batches and exits cleanly. Any in-progress child run will
    finish (we don't try to kill a mid-flight Claude session).
    """
    job = db.get(BackfillJob, job_id)
    if job is None:
        raise HTTPException(status_code=404)
    tenant = db.get(Tenant, job.tenant_id)
    if tenant is None or tenant.user_id != user.id:
        raise HTTPException(status_code=404)
    if job.status not in ("queued", "running"):
        raise HTTPException(status_code=400, detail=f"Job is already {job.status}")

    job.status = "cancelled"
    job.error_message = "Cancellation requested by user; will stop after the current batch."
    db.commit()
    db.refresh(job)
    return job


@router.get("/tenants/{tenant_id}/backfills", response_model=list[BackfillJobOut])
def list_backfills(
    tenant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    _owned_tenant(db, user, tenant_id)
    return (
        db.query(BackfillJob)
        .filter(BackfillJob.tenant_id == tenant_id)
        .order_by(BackfillJob.id.desc())
        .all()
    )


# ---------------------------------------------------------------------------
# /api/tenants/{id}/chat — interactive Claude chat with Zuora MCP
# ---------------------------------------------------------------------------

SKILL_WORKDIR = Path(__file__).resolve().parents[3] / "skill_workdir"

CHAT_ALLOWED_TOOLS: list[str] = [
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
    "mcp__zuora-developer-mcp",
]

CHAT_SYSTEM_PROMPT = (
    "You are a Zuora expert assistant connected to a live {environment} sandbox "
    "tenant ({tenant_name}). You have full access to Zuora MCP tools for "
    "querying and modifying data in this tenant, plus Bash for running the "
    "zuora_helpers.py SDK script. Help the user with their questions — be "
    "concise, show your work via tool calls, and explain what you find. "
    "When the user asks about data, always query Zuora first rather than "
    "guessing. Format results as clean markdown tables when appropriate."
)


class ChatRequest(PydanticBaseModel):
    message: str
    session_id: str     # client-generated UUID, reused across turns
    is_new: bool = True # True on the first message of a new conversation


@router.post("/tenants/{tenant_id}/chat")
async def tenant_chat(
    tenant_id: int,
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """
    Interactive chat with Claude connected to the tenant's Zuora MCP.

    POST a message + session_id, receive a streaming SSE response. The
    session_id links turns together — the Claude Agent SDK remembers the
    conversation across calls with the same session_id.

    SSE events:
      - event: text       → {text: "..."}
      - event: tool_use   → {id, name, input}
      - event: thinking   → {text: "(thinking)"}
      - event: error      → {message: "..."}
      - event: done       → {stop_reason, cost_usd}
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        SystemMessage,
        TextBlock,
        ThinkingBlock,
        ToolResultBlock,
        ToolUseBlock,
        query,
    )
    from app.runner import _redact

    tenant = _owned_tenant(db, user, tenant_id)

    try:
        client_secret = decrypt(tenant.client_secret_encrypted)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Decrypt failed: {e}") from e

    system_prompt = CHAT_SYSTEM_PROMPT.format(
        environment=tenant.environment,
        tenant_name=tenant.name,
    )

    # First message of a new conversation: session_id=<uuid> (creates the session).
    # Subsequent messages: resume=<uuid> (continues the existing session).
    session_kwargs: dict = (
        {"session_id": body.session_id}
        if body.is_new
        else {"resume": body.session_id}
    )

    options = ClaudeAgentOptions(
        cwd=str(SKILL_WORKDIR),
        system_prompt=system_prompt if body.is_new else None,
        **session_kwargs,
        env={
            "ZUORA_CLIENT_ID": tenant.client_id,
            "ZUORA_CLIENT_SECRET": client_secret,
            "ZUORA_ENVIRONMENT": tenant.environment,
            "ZUORA_BASE_URL": tenant.base_url,
            **({"ANTHROPIC_API_KEY": settings.ANTHROPIC_API_KEY} if settings.ANTHROPIC_API_KEY else {}),
        },
        mcp_servers={
            "zuora-developer-mcp": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "zuora-mcp"],
                "env": {
                    "ZUORA_CLIENT_ID": tenant.client_id,
                    "ZUORA_CLIENT_SECRET": client_secret,
                    "BASE_URL": tenant.base_url,
                    "APPROVAL_ENABLED": "false",
                },
            },
        },
        allowed_tools=CHAT_ALLOWED_TOOLS,
        permission_mode="bypassPermissions",
    )

    async def generate():
        try:
            async for message in query(prompt=body.message, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            yield _sse("text", {"text": block.text})
                        elif isinstance(block, ToolUseBlock):
                            yield _sse(
                                "tool_use",
                                {
                                    "id": block.id,
                                    "name": block.name,
                                    "input": _redact(block.input),
                                },
                            )
                        elif isinstance(block, ToolResultBlock):
                            content = (
                                block.content
                                if isinstance(block.content, str)
                                else str(block.content)
                            )
                            yield _sse(
                                "tool_result",
                                {
                                    "tool_use_id": block.tool_use_id if hasattr(block, "tool_use_id") else None,
                                    "content": content[:4000],
                                    "is_error": bool(block.is_error),
                                },
                            )
                        elif isinstance(block, ThinkingBlock):
                            yield _sse("thinking", {"text": "(thinking)"})
                elif isinstance(message, ResultMessage):
                    yield _sse(
                        "done",
                        {
                            "stop_reason": message.stop_reason,
                            "cost_usd": message.total_cost_usd,
                        },
                    )
                # SystemMessage, UserMessage, StreamEvent: skip
        except Exception as e:  # noqa: BLE001
            yield _sse("error", {"message": f"{type(e).__name__}: {e}"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# /api/tenants/{id}/billing — interactive billing & payments
# ---------------------------------------------------------------------------


class BillRunRequest(PydanticBaseModel):
    target_date: str  # ISO date string
    invoice_date: str | None = None


class ApplyPaymentsRequest(PydanticBaseModel):
    class PaymentItem(PydanticBaseModel):
        invoice_id: str
        account_id: str
        amount: float
        effective_date: str  # ISO date string
        currency: str = "USD"
    payments: list[PaymentItem]


class WriteOffRequest(PydanticBaseModel):
    invoice_id: str
    amount: float
    reason_code: str = "Write-off"
    comment: str = "Small balance write-off"


@router.post("/tenants/{tenant_id}/billing/run")
async def trigger_bill_run(
    tenant_id: int,
    body: BillRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Trigger an ad-hoc bill run in Zuora."""
    from datetime import date as date_type
    from app.billing import create_bill_run, BillingError

    tenant = _owned_tenant(db, user, tenant_id)
    try:
        target = date_type.fromisoformat(body.target_date)
        inv_date = date_type.fromisoformat(body.invoice_date) if body.invoice_date else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date: {e}") from e
    try:
        result = await create_bill_run(tenant, target, inv_date)
    except BillingError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return result


@router.get("/tenants/{tenant_id}/billing/run-status/{bill_run_id}")
async def poll_bill_run_status(
    tenant_id: int,
    bill_run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Poll bill run status until completed."""
    from app.billing import get_bill_run_status, BillingError

    tenant = _owned_tenant(db, user, tenant_id)
    try:
        return await get_bill_run_status(tenant, bill_run_id)
    except BillingError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/tenants/{tenant_id}/billing/open-invoices")
async def fetch_open_invoices(
    tenant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Fetch all open (posted, balance > 0) invoices from Zuora."""
    from app.billing import get_open_invoices, BillingError

    tenant = _owned_tenant(db, user, tenant_id)
    try:
        invoices = await get_open_invoices(tenant)
    except BillingError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return invoices


@router.post("/tenants/{tenant_id}/billing/apply-payments")
async def apply_payments(
    tenant_id: int,
    body: ApplyPaymentsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Apply payments to one or more invoices."""
    from datetime import date as date_type
    from app.billing import apply_payment, BillingError

    tenant = _owned_tenant(db, user, tenant_id)
    results = []
    errors = []
    for item in body.payments:
        try:
            eff_date = date_type.fromisoformat(item.effective_date)
            result = await apply_payment(
                tenant,
                account_id=item.account_id,
                invoice_id=item.invoice_id,
                amount=item.amount,
                effective_date=eff_date,
                currency=item.currency,
            )
            results.append(result)
        except (BillingError, Exception) as e:
            errors.append({
                "invoice_id": item.invoice_id,
                "error": str(e),
            })
    return {"results": results, "errors": errors}


@router.post("/tenants/{tenant_id}/billing/write-off")
async def create_write_off_endpoint(
    tenant_id: int,
    body: WriteOffRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Create a credit memo write-off for an invoice."""
    from app.billing import create_write_off, BillingError

    tenant = _owned_tenant(db, user, tenant_id)
    try:
        result = await create_write_off(
            tenant,
            invoice_id=body.invoice_id,
            amount=body.amount,
            reason_code=body.reason_code,
            comment=body.comment,
        )
    except BillingError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return result


# ---------------------------------------------------------------------------
# Health check — unauthenticated, always returns 200
# ---------------------------------------------------------------------------

@router.get("/health")
def health():
    return {"status": "ok"}


