"""
APScheduler integration for per-tenant cron schedules.

Design:
  - A single AsyncIOScheduler runs inside the uvicorn event loop.
  - The Schedule table is the source of truth; APScheduler's job store is
    in-memory and is rebuilt from the DB on startup.
  - All create/update/delete routes call `sync_schedule` / `remove_schedule`
    so APScheduler's state stays in lockstep with the DB.
  - When a cron fires, `_fire_scheduled_run` creates a Run row with
    trigger="schedule" and hands it off to the Phase 2 runner (same path a
    manual "Run now" click takes). The runner's pre-run validator still
    applies, so a scheduled run against a broken config lands in the DB as
    status=failed with the same explanatory error — no surprises.
  - Concurrency: if a previous run for the same tenant is still in flight
    when the next cron fires, we create a skipped Run row (trigger=
    "schedule", status="failed", error_message="previous run still running")
    instead of spawning a duplicate. Stops runaway parallel runs against a
    single tenant.

Timezone:
  AsyncIOScheduler is created with the server's local timezone by default,
  which is fine for a self-hosted internal tool. The UI documents this.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import SessionLocal
from app.models import Run, Schedule, Tenant


logger = logging.getLogger("zuora-se-agent.scheduler")


# Single global scheduler instance. Created lazily so tests that don't
# touch scheduling don't accidentally start a background loop.
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


async def start_scheduler() -> None:
    """
    Start the scheduler and register every enabled schedule from the DB.
    Called from the FastAPI lifespan startup hook.
    """
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("scheduler started")

    with SessionLocal() as db:
        enabled = db.query(Schedule).filter(Schedule.enabled.is_(True)).all()
        for s in enabled:
            try:
                _register_job(s)
            except Exception:  # noqa: BLE001
                logger.exception("failed to register schedule-%s on startup", s.id)
        logger.info("registered %d enabled schedule(s) on startup", len(enabled))


async def stop_scheduler() -> None:
    """Stop the scheduler. Called from the FastAPI lifespan shutdown hook."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler stopped")


# ------------------------------------------------------------------
# Cron parsing / preview
# ------------------------------------------------------------------


class CronParseError(ValueError):
    pass


def parse_cron(cron: str) -> CronTrigger:
    """Parse a 5-field cron expression into a CronTrigger. Raises CronParseError."""
    cron = (cron or "").strip()
    if not cron:
        raise CronParseError("Cron expression is empty")
    try:
        return CronTrigger.from_crontab(cron)
    except Exception as e:  # noqa: BLE001
        raise CronParseError(f"Invalid cron expression: {e}") from e


def next_fire_times(cron: str, count: int = 3) -> list[datetime]:
    """
    Return the next N fire times for a cron expression (for UI preview).

    APScheduler's `get_next_fire_time(previous_fire_time, now)` takes
    `min(now, previous + 1µs)` as the search start, so if both are in
    the future, `now` wins and the search resets to "next fire from now"
    — meaning you get the same timestamp on every iteration. Workaround:
    advance `now` past the last fire on each pass instead of setting
    `previous_fire_time`.
    """
    from datetime import timedelta

    trigger = parse_cron(cron)
    cursor = datetime.now().astimezone()
    out: list[datetime] = []
    for _ in range(count):
        nxt = trigger.get_next_fire_time(None, cursor)
        if nxt is None:
            break
        out.append(nxt)
        cursor = nxt + timedelta(microseconds=1)
    return out


def next_fire_time(cron: str) -> datetime | None:
    """Single next fire time, or None if the cron never fires again."""
    times = next_fire_times(cron, count=1)
    return times[0] if times else None


# ------------------------------------------------------------------
# Sync DB ↔ APScheduler
# ------------------------------------------------------------------


def _job_id(schedule_id: int) -> str:
    return f"schedule-{schedule_id}"


def _register_job(sched: Schedule) -> None:
    """Register (or replace) an APScheduler job for a schedule row."""
    trigger = parse_cron(sched.cron)
    scheduler = get_scheduler()
    scheduler.add_job(
        _fire_scheduled_run,
        trigger=trigger,
        args=[sched.id],
        id=_job_id(sched.id),
        name=f"zuora-se-agent schedule-{sched.id} ({sched.cron})",
        replace_existing=True,
        coalesce=True,          # collapse missed fires into one
        max_instances=1,        # belt-and-suspenders against overlap
        misfire_grace_time=300, # 5 min grace
    )


def sync_schedule(schedule_id: int) -> None:
    """
    Ensure APScheduler's state matches the DB for this schedule.
    Called from routers after create/update.
    """
    with SessionLocal() as db:
        sched = db.get(Schedule, schedule_id)
        if sched is None:
            remove_schedule(schedule_id)
            return

        scheduler = get_scheduler()
        if not scheduler.running:
            # Scheduler not started yet (e.g. tests) — the startup hook
            # will load this row when it runs.
            sched.next_run_at = next_fire_time(sched.cron) if sched.enabled else None
            db.commit()
            return

        if sched.enabled:
            _register_job(sched)
            sched.next_run_at = next_fire_time(sched.cron)
        else:
            remove_schedule(schedule_id)
            sched.next_run_at = None
        db.commit()


def remove_schedule(schedule_id: int) -> None:
    """Remove the APScheduler job for a schedule. Safe to call if absent."""
    scheduler = get_scheduler()
    if not scheduler.running:
        return
    try:
        scheduler.remove_job(_job_id(schedule_id))
    except Exception:  # noqa: BLE001
        pass  # job didn't exist — fine


# ------------------------------------------------------------------
# Scheduled fire callback
# ------------------------------------------------------------------


async def _fire_scheduled_run(schedule_id: int) -> None:
    """
    Fire handler invoked by APScheduler when a schedule's cron matches.

    Creates a Run row with trigger="schedule" and hands it to the runner.
    Refuses to spawn a duplicate run if an earlier one for the same tenant
    is still in flight — records a skipped Run row instead so users can
    see the decision in history.
    """
    # Import lazily to avoid a circular import at module load time:
    # runner → tenant_config → models → (...), and scheduler pulls runner.
    from app.runner import start_run_in_background

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        sched = db.get(Schedule, schedule_id)
        if sched is None or not sched.enabled:
            logger.info("schedule-%s fired but is disabled/missing; ignoring", schedule_id)
            return

        tenant = db.get(Tenant, sched.tenant_id)
        if tenant is None:
            logger.warning("schedule-%s fired but tenant is gone; disabling", schedule_id)
            sched.enabled = False
            db.commit()
            remove_schedule(schedule_id)
            return

        # Concurrency guards: refuse to start a new run if any earlier run
        # for this tenant is still queued/running OR if a backfill job is
        # active on this tenant (during a backfill the tenant is held).
        from app.backfill import find_in_flight_backfill

        in_flight = (
            db.query(Run)
            .filter(
                Run.tenant_id == tenant.id,
                Run.status.in_(("queued", "running")),
            )
            .first()
        )
        blocking_job = (
            find_in_flight_backfill(db, tenant.id) if in_flight is None else None
        )

        if in_flight is not None or blocking_job is not None:
            reason = (
                f"run-{in_flight.id} was still {in_flight.status}"
                if in_flight is not None
                else (
                    f"backfill-{blocking_job.id} is {blocking_job.status} "
                    f"({blocking_job.completed_batches}/{blocking_job.total_batches} "
                    "batches done)"
                )
            )
            skipped = Run(
                tenant_id=tenant.id,
                triggered_by_user_id=None,
                trigger="schedule",
                status="failed",
                started_at=now,
                finished_at=now,
                error_message=(
                    f"Schedule {schedule_id} fired but {reason}. Skipped "
                    "to prevent concurrent mutations on the same tenant."
                ),
            )
            db.add(skipped)
            sched.last_run_at = now
            sched.next_run_at = next_fire_time(sched.cron)
            db.commit()
            logger.info("schedule-%s skipped: %s", schedule_id, reason)
            return

        run = Run(
            tenant_id=tenant.id,
            triggered_by_user_id=None,
            trigger="schedule",
            status="queued",
            started_at=now,
        )
        db.add(run)
        sched.last_run_at = now
        sched.next_run_at = next_fire_time(sched.cron)
        db.commit()
        db.refresh(run)
        run_id = run.id

    logger.info("schedule-%s fired → run-%s", schedule_id, run_id)
    start_run_in_background(run_id)
