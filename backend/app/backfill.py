"""
Backfill coordinator — runs a BackfillJob end-to-end.

Flow:
  1. Caller (the API route) creates a BackfillJob row in status="queued"
     after validating the date range. It then calls
     `start_backfill_in_background(job_id)`.
  2. That schedules `_execute_backfill(job_id)` as an asyncio task on the
     running event loop. The route returns immediately.
  3. `_execute_backfill` computes the list of batch dates from the job's
     range + granularity, then loops serially. For each date it:
        a. Creates a Run row with trigger="backfill", backfill_date=<that date>,
           parent_job_id=<this job>, triggered_by_user_id=<job owner>
        b. Awaits `runner._execute_run(run_id)` inline — we don't fire-and-
           forget because we need the result before starting the next batch.
        c. If the Run finishes with status="failed", the whole job is
           marked failed and the loop stops. Remaining batches don't run.
        d. Otherwise increment `completed_batches` and continue.
  4. When the loop finishes naturally, the job is marked succeeded.

Why serial not parallel:
  The runner's concurrency guard already refuses to start a new run for
  a tenant with another run in flight. Running batches in parallel would
  just produce a pile of "skipped" rows. Serial also makes the "this
  month builds on last month's data" narrative work the way you'd expect.

Why await _execute_run directly instead of going through start_run_in_background:
  The background version fires and forgets — we'd have to poll the DB for
  completion. Awaiting the async function directly gives us the completion
  signal for free.
"""
from __future__ import annotations

import asyncio
import logging
from calendar import monthrange
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import BackfillJob, Run, Tenant


logger = logging.getLogger("zuora-se-agent.backfill")


# ------------------------------------------------------------------
# Batch date generation
# ------------------------------------------------------------------


def compute_batch_dates(
    start: datetime, end: datetime, granularity: str = "monthly"
) -> list[datetime]:
    """
    Return the list of "effective dates" to use for each batch.

    For monthly granularity we pick the first day of each month in the
    inclusive range [start..end]. So a job covering 2025-04-15 through
    2026-04-15 produces:
      [2025-04-01, 2025-05-01, ..., 2026-04-01]
    which is 13 batches. Using the 1st of the month makes the timeline
    tidy and avoids edge cases around months with different day counts.
    """
    if granularity != "monthly":
        raise ValueError(f"unsupported granularity: {granularity!r}")

    # SQLite strips tzinfo when storing DateTime(timezone=True), so we may
    # receive naive datetimes from the DB even though the column "has"
    # timezone. Treat every naive datetime here as UTC — that's how we
    # wrote it, and it's what every caller expects. Without this coercion,
    # .astimezone() on a naive datetime interprets it as local time and
    # can shift month boundaries across the dateline.
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    if end < start:
        raise ValueError("end is before start")

    # Normalize both ends to day boundaries in UTC so we don't drift on
    # timezone arithmetic across month boundaries.
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)

    out: list[datetime] = []
    y, m = start_utc.year, start_utc.month
    while True:
        candidate = datetime(y, m, 1, tzinfo=timezone.utc)
        if candidate > end_utc:
            break
        out.append(candidate)
        # Advance one month
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
    return out


def default_label(start: datetime, end: datetime) -> str:
    return f"Backfill {start.strftime('%Y-%m')} → {end.strftime('%Y-%m')}"


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------


def start_backfill_in_background(job_id: int) -> None:
    """
    Fire-and-forget. Caller must already be inside a running event loop
    (which FastAPI route handlers are).
    """
    loop = asyncio.get_running_loop()
    loop.create_task(_execute_backfill(job_id), name=f"backfill-{job_id}")


# ------------------------------------------------------------------
# Core loop
# ------------------------------------------------------------------


async def _execute_backfill(job_id: int) -> None:
    """Run a backfill job to completion. Never raises — errors land in the DB."""
    # Local import to avoid a circular (runner → backfill → runner).
    from app.runner import _execute_run

    # --- Load job + compute batch plan ---
    with SessionLocal() as db:
        job = db.get(BackfillJob, job_id)
        if job is None:
            logger.error("backfill-%d disappeared before execution", job_id)
            return
        tenant = db.get(Tenant, job.tenant_id)
        if tenant is None:
            _finalize_job(
                db, job, status="failed", error="Tenant no longer exists"
            )
            return

        try:
            batch_dates = compute_batch_dates(
                job.start_date, job.end_date, job.granularity
            )
        except ValueError as e:
            _finalize_job(db, job, status="failed", error=f"Bad plan: {e}")
            return

        if not batch_dates:
            _finalize_job(
                db, job, status="failed", error="Date range produced zero batches"
            )
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.total_batches = len(batch_dates)
        job.completed_batches = 0
        db.commit()
        tenant_id = tenant.id
        owner_id = job.triggered_by_user_id
        label = job.label or default_label(job.start_date, job.end_date)

    logger.info(
        "backfill-%d starting: tenant=%d batches=%d label=%r",
        job_id,
        tenant_id,
        len(batch_dates),
        label,
    )

    # --- Serial execution ---
    for idx, batch_date in enumerate(batch_dates, start=1):
        # Create the child Run row for this batch.
        with SessionLocal() as db:
            run = Run(
                tenant_id=tenant_id,
                triggered_by_user_id=owner_id,
                trigger="backfill",
                status="queued",
                started_at=datetime.now(timezone.utc),
                backfill_date=batch_date,
                parent_job_id=job_id,
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            child_id = run.id

        logger.info(
            "backfill-%d batch %d/%d: run-%d for %s",
            job_id,
            idx,
            len(batch_dates),
            child_id,
            batch_date.strftime("%Y-%m-%d"),
        )

        # Run it to completion. _execute_run swallows its own exceptions
        # and always updates run.status to a terminal value, so we only
        # need to read the final status from the DB.
        try:
            await _execute_run(child_id)
        except Exception:  # noqa: BLE001 — defensive; _execute_run shouldn't raise
            logger.exception("backfill-%d: batch %d unexpected crash", job_id, idx)

        # Check outcome
        with SessionLocal() as db:
            run = db.get(Run, child_id)
            job = db.get(BackfillJob, job_id)
            if job is None:
                logger.warning("backfill-%d vanished mid-run; stopping", job_id)
                return

            if job.status == "cancelled":
                _finalize_job(
                    db,
                    job,
                    status="cancelled",
                    error="Job was cancelled by the user.",
                )
                return

            if run is None or run.status == "failed":
                err = (
                    run.error_message if run is not None else "Child run disappeared"
                )
                _finalize_job(
                    db,
                    job,
                    status="failed",
                    error=(
                        f"Batch {idx}/{len(batch_dates)} "
                        f"({batch_date.strftime('%Y-%m-%d')}) failed:\n\n{err}"
                    ),
                )
                logger.info(
                    "backfill-%d: stopping after batch %d failure", job_id, idx
                )
                return

            job.completed_batches = idx
            db.commit()

    # --- All batches done ---
    with SessionLocal() as db:
        job = db.get(BackfillJob, job_id)
        if job is not None:
            _finalize_job(db, job, status="succeeded")
    logger.info("backfill-%d done: all %d batches succeeded", job_id, len(batch_dates))


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _finalize_job(
    db: Session,
    job: BackfillJob,
    *,
    status: str,
    error: str = "",
) -> None:
    job.status = status
    job.finished_at = datetime.now(timezone.utc)
    if error:
        job.error_message = error
    db.commit()


def find_in_flight_backfill(db: Session, tenant_id: int) -> BackfillJob | None:
    """
    Return the first queued/running backfill job for a tenant, or None.
    Used by the concurrency guards in runner.py and scheduler.py so that
    manual runs and scheduled fires are blocked while a backfill is active.
    """
    return (
        db.query(BackfillJob)
        .filter(
            BackfillJob.tenant_id == tenant_id,
            BackfillJob.status.in_(("queued", "running")),
        )
        .order_by(BackfillJob.id.asc())
        .first()
    )
