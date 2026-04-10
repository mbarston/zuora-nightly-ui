"""
Run a tenant's nightly skill execution via the Claude Agent SDK.

Flow:
  1. Caller creates a Run row in status="queued" and hands the run_id to
     `start_run_in_background(run_id)`.
  2. That schedules `_execute_run(run_id)` as an asyncio task on the running
     event loop. We don't block the request.
  3. `_execute_run` loads the Run + Tenant in a fresh sync DB session,
     decrypts the tenant client_secret, builds ClaudeAgentOptions, and runs
     `query()` end-to-end. Each message is turned into a RunEvent row.
  4. On completion, the Run row is updated with status, summary_md, and
     error_message. On exception, status="failed" + traceback in error_message.

Per-tenant isolation:
  - The decrypted client_secret lives only in memory for the duration of
     the run — never logged, never written to RunEvent payloads.
  - The zuora-mcp stdio server is launched as a subprocess with its own env
     dict, so other tenants' credentials can't leak in.
  - cwd is a read-only baked-in skill workdir under backend/skill_workdir/.
     Any disk writes the agent attempts will go there, which is fine since
     the skill doesn't need to write anything permanent to the filesystem.
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.backfill import find_in_flight_backfill
from app.config import settings
from app.crypto import decrypt
from app.db import SessionLocal
from app.models import Run, RunEvent, Tenant, TenantConfig
from app.tenant_config import has_errors, to_prompt_markdown, validate


class RunConflictError(RuntimeError):
    """
    Raised by start_manual_run when another run for the same tenant is
    already queued or running. Routers catch this and render a clean
    409-style message.
    """

    def __init__(self, tenant_id: int, blocking_run_id: int, blocking_status: str):
        super().__init__(
            f"Tenant {tenant_id} already has run-{blocking_run_id} "
            f"in status '{blocking_status}'."
        )
        self.tenant_id = tenant_id
        self.blocking_run_id = blocking_run_id
        self.blocking_status = blocking_status


def find_in_flight_run(db: Session, tenant_id: int) -> Run | None:
    """Return the oldest queued/running run for a tenant, or None."""
    return (
        db.query(Run)
        .filter(
            Run.tenant_id == tenant_id,
            Run.status.in_(("queued", "running")),
        )
        .order_by(Run.id.asc())
        .first()
    )


def find_concurrency_blocker(db: Session, tenant_id: int) -> str | None:
    """
    Is there anything preventing us from starting a new manual/scheduled run
    for this tenant? Returns a human-readable reason, or None if clear.

    Checks both in-flight Runs and in-flight BackfillJobs — during a
    backfill we hold the whole tenant so manual and scheduled runs can't
    interleave historical batches with current-day writes.
    """
    in_flight = find_in_flight_run(db, tenant_id)
    if in_flight is not None:
        return f"run-{in_flight.id} is already {in_flight.status}"

    job = find_in_flight_backfill(db, tenant_id)
    if job is not None:
        return (
            f"backfill-{job.id} is {job.status} "
            f"({job.completed_batches}/{job.total_batches} batches done)"
        )
    return None


logger = logging.getLogger("zuora-se-agent.runner")


# Path to the baked-in skill directory. The SDK will load
# .claude/skills/zuora-demo-data-nightly/SKILL.md from here when
# setting_sources=["project"] is passed.
SKILL_WORKDIR = Path(__file__).resolve().parents[1] / "skill_workdir"


# Tools the skill is allowed to use. Matches the GitHub Actions workflow's
# allowlist exactly, minus nothing. Wildcard for zuora MCP tools so the
# agent can use any of them.
ALLOWED_TOOLS: list[str] = [
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
    "TodoWrite",
    "mcp__zuora-developer-mcp",  # full MCP namespace — the SDK expands this
]


RUN_PROMPT_HEADER = (
    "Run the zuora-demo-data-nightly skill end-to-end. Work through all four "
    "steps in the SKILL.md file (discovery, plan, execute, report). When "
    "complete, print the full markdown report as your FINAL message — do NOT "
    "write it to a file. The calling system captures your final message text "
    "as the run's report.\n\n"
    "The tenant configuration below is the AUTHORITATIVE source for product "
    "rate plan IDs, mandatory usage subscriptions, volume ranges, and mix "
    "percentages. Any example values inside SKILL.md are reference-only and "
    "MUST NOT be used in place of these values.\n\n"
)


def _backfill_window_markdown(backfill_date: datetime) -> str:
    """
    Build the "## Backfill window" section that gets appended to the run
    prompt when this run is part of a historical backfill.

    The skill normally picks today's date for every Zuora operation. For
    backfill batches we tell it to pretend a different date is "today"
    and push that date through every field that accepts a timestamp:
      - create_subscriptions: orderDate + the initial term's start date
      - Amendments: contractEffectiveDate + all three triggerDates
      - cancel_subscriptions: orderDate + cancellationEffectiveDate
      - Usage posts: StartDateTime (with a realistic time-of-day)
    """
    date_str = backfill_date.strftime("%Y-%m-%d")
    return (
        "## Backfill window\n"
        "\n"
        f"**IMPORTANT**: This is a historical backfill run. Pretend the "
        f"current date is **{date_str}** for every Zuora operation in this "
        "run. Every timestamp you pass to Zuora must land on or near that "
        "date, NOT today's real calendar date.\n"
        "\n"
        "Concrete rules:\n"
        "\n"
        f"1. **New subscriptions** (`create_subscriptions`): set `orderDate` "
        f"to `{date_str}` and leave the initial term's start date to derive "
        "from that (the skill's usual per-tenant-config logic still applies).\n"
        f"2. **Amendments** (`add-product`, `remove-product`, `change-plan`, "
        f"`update-product`): when calling `zuora_helpers.py`, the helper uses "
        f"today's date internally. For backfill runs you MUST instead call "
        f"the underlying Zuora SDK / MCP tool directly so you can pass "
        f"`contractEffectiveDate={date_str}` and all three trigger dates "
        f"(`ContractEffective`, `ServiceActivation`, `CustomerAcceptance`) "
        f"set to `{date_str}`. Do not use the helper's shortcut commands for "
        f"this run.\n"
        f"3. **Cancellations** (`cancel_subscriptions`): set both `orderDate` "
        f"and `cancellationEffectiveDate` to `{date_str}`. Use "
        f"`cancellationPolicy: \"SpecificDate\"` because the default "
        f"`EndOfCurrentTerm` will resolve to a future date that breaks the "
        f"historical narrative.\n"
        f"4. **Usage posts** (`post-usage`): pass `--start-date "
        f"{date_str}T10:00:00.000+00:00` (or any mid-day time) to "
        f"`zuora_helpers.py post-usage`. Don't let it default to `now`.\n"
        "\n"
        "Volume targets and mix percentages from the tenant config section "
        "above still apply exactly — a backfill batch should produce the "
        "same number of actions as a normal daily run, just backdated. The "
        "skill's data-story rules (growth outpacing churn, tier mix, etc.) "
        "also still apply to this batch independently.\n"
        "\n"
        "When writing the final report, clearly label it as a backfill "
        f"batch for {date_str} so it's distinguishable from regular runs "
        "in history.\n"
    )


# ------------------------------------------------------------------
# Entry point + task tracking
# ------------------------------------------------------------------

# Global registry of in-flight asyncio tasks keyed by run_id.
# Used by cancel_run() to abort a running execution.
_active_tasks: dict[int, asyncio.Task] = {}


def start_run_in_background(run_id: int) -> None:
    """
    Fire-and-forget. Caller must already be inside a running event loop
    (which FastAPI route handlers are).
    """
    loop = asyncio.get_running_loop()
    task = loop.create_task(_execute_run(run_id), name=f"run-{run_id}")
    _active_tasks[run_id] = task
    task.add_done_callback(lambda _t: _active_tasks.pop(run_id, None))


def cancel_run(run_id: int) -> bool:
    """
    Cancel an in-flight run. Returns True if the task was found and
    cancelled, False if there was no active task (already finished or
    never started).
    """
    task = _active_tasks.get(run_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


# ------------------------------------------------------------------
# Core execution
# ------------------------------------------------------------------


async def _execute_run(run_id: int) -> None:
    """Execute a single run end-to-end. Never raises — errors land in the DB."""
    # Import lazily so the rest of the app works even if claude_agent_sdk
    # isn't importable (e.g. during tests).
    try:
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
    except ImportError as e:
        _mark_failed(run_id, f"claude-agent-sdk is not installed: {e}")
        return

    # --- Load run + tenant + config ---
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if run is None:
            logger.error("run %d disappeared before execution", run_id)
            return
        tenant = db.get(Tenant, run.tenant_id)
        if tenant is None:
            _finalize(db, run, status="failed", error="Tenant no longer exists")
            return

        # Concurrency guard — refuse to start if any OTHER run for the
        # same tenant is queued/running. This is a belt-and-suspenders
        # check; the POST /runs handler also enforces it, but the
        # scheduler can race against manual runs and we want to catch it
        # here too. We only look for runs with id != this one so a run
        # can't see itself as "in flight".
        #
        # Backfill exception: when THIS run is a backfill child, the
        # parent BackfillJob is what's running. We ALLOW the run to
        # proceed even though a backfill is in flight (because we ARE
        # that backfill). The coordinator executes batches serially, so
        # there will never be two backfill children queued at once.
        other_in_flight = (
            db.query(Run)
            .filter(
                Run.tenant_id == tenant.id,
                Run.id != run.id,
                Run.status.in_(("queued", "running")),
            )
            .order_by(Run.id.asc())
            .first()
        )
        if other_in_flight is not None:
            _finalize(
                db,
                run,
                status="failed",
                error=(
                    f"Skipped: run-{other_in_flight.id} was still "
                    f"{other_in_flight.status} when this run started."
                ),
            )
            logger.info(
                "run-%d blocked by concurrency guard (run-%d still %s)",
                run.id,
                other_in_flight.id,
                other_in_flight.status,
            )
            return

        if run.parent_job_id is None:
            # Not a backfill child. Also refuse if any backfill is active
            # on this tenant — the backfill owns the tenant until done.
            blocking_job = find_in_flight_backfill(db, tenant.id)
            if blocking_job is not None:
                _finalize(
                    db,
                    run,
                    status="failed",
                    error=(
                        f"Skipped: backfill-{blocking_job.id} is "
                        f"{blocking_job.status} "
                        f"({blocking_job.completed_batches}/{blocking_job.total_batches} batches done)."
                    ),
                )
                logger.info(
                    "run-%d blocked by backfill-%d",
                    run.id,
                    blocking_job.id,
                )
                return

        tenant_config = (
            db.query(TenantConfig).filter(TenantConfig.tenant_id == tenant.id).one_or_none()
        )

        # Pre-run validation gate — refuse to run a broken config rather
        # than waste API credit on a guaranteed-broken skill invocation.
        issues = validate(tenant_config)
        if has_errors(issues):
            error_lines = ["Config validation failed — run refused:", ""]
            for iss in issues:
                if iss.severity == "error":
                    error_lines.append(f"  ✗ [{iss.field}] {iss.message}")
            _finalize(db, run, status="failed", error="\n".join(error_lines))
            logger.info("run-%d blocked by pre-run validation", run.id)
            return

        try:
            client_secret = decrypt(tenant.client_secret_encrypted)
        except Exception as e:  # noqa: BLE001
            _finalize(db, run, status="failed", error=f"Failed to decrypt credentials: {e}")
            return

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        db.commit()

        # Build the full prompt: header + serialized per-tenant config.
        assert tenant_config is not None  # validate() would have erred otherwise
        prompt_text = RUN_PROMPT_HEADER + to_prompt_markdown(tenant.name, tenant_config)

        # Backfill window: when run.backfill_date is set, the runner is a
        # child of a BackfillJob. Tell the skill to pretend that date is
        # "today" so orderDate, contractEffectiveDate, cancellationEffectiveDate,
        # and usage StartDateTime are all backdated to that month.
        if run.backfill_date is not None:
            prompt_text += "\n\n" + _backfill_window_markdown(run.backfill_date)

        tenant_env = {
            "ZUORA_CLIENT_ID": tenant.client_id,
            "ZUORA_CLIENT_SECRET": client_secret,
            "ZUORA_ENVIRONMENT": tenant.environment,
            "ZUORA_BASE_URL": tenant.base_url,
        }
        mcp_env = {
            "ZUORA_CLIENT_ID": tenant.client_id,
            "ZUORA_CLIENT_SECRET": client_secret,
            "BASE_URL": tenant.base_url,
            "APPROVAL_ENABLED": "false",
        }
        run_label = f"run-{run.id} tenant={tenant.name!r}"

    # --- Build options ---
    # Capture stderr from the bundled CLI so we can diagnose failures.
    stderr_lines: list[str] = []
    def _on_stderr(line: str) -> None:
        stderr_lines.append(line)
        logger.debug("[%s] CLI stderr: %s", run_label, line)

    options = ClaudeAgentOptions(
        cwd=str(SKILL_WORKDIR),
        env={
            **tenant_env,
            # Inherit the shared Anthropic key from the backend's env.
            # (asyncio.subprocess inherits os.environ by default, so this
            # is mostly belt-and-suspenders — makes the key explicit.)
            **({"ANTHROPIC_API_KEY": settings.ANTHROPIC_API_KEY} if settings.ANTHROPIC_API_KEY else {}),
        },
        mcp_servers={
            "zuora-developer-mcp": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "zuora-mcp"],
                "env": mcp_env,
            },
        },
        allowed_tools=ALLOWED_TOOLS,
        permission_mode="bypassPermissions",
        # Load .claude/skills/ from cwd so SKILL.md is auto-discovered.
        setting_sources=["project"],
        stderr=_on_stderr,
    )

    # --- Pre-flight checks ---
    import os
    api_key = settings.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        _mark_failed(run_id, "ANTHROPIC_API_KEY is not set. Set it via `fly secrets set ANTHROPIC_API_KEY=sk-ant-...`")
        return
    logger.info("[%s] starting (API key length=%d, cwd=%s)", run_label, len(api_key), SKILL_WORKDIR)

    # --- Stream ---
    seq = 0
    final_text: str | None = None
    total_cost_usd: float | None = None
    try:
        async for message in query(prompt=prompt_text, options=options):
            # Process each message, persisting events as we go. We open a
            # short-lived session per message to keep the transaction tight.
            try:
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        seq = _persist_block(run_id, seq, block)
                        if isinstance(block, TextBlock):
                            final_text = block.text  # last text wins
                elif isinstance(message, ResultMessage):
                    seq = _persist_event(
                        run_id,
                        seq,
                        "result",
                        {
                            "stop_reason": message.stop_reason,
                            "cost_usd": message.total_cost_usd,
                            "result": (message.result or "")[:4000],
                            "errors": message.errors or [],
                        },
                    )
                    if message.total_cost_usd is not None:
                        total_cost_usd = float(message.total_cost_usd)
                    if message.result:
                        final_text = message.result
                elif isinstance(message, SystemMessage):
                    # SystemMessage carries init info — record it coarsely.
                    seq = _persist_event(run_id, seq, "system", {"note": "system message"})
                # UserMessage, StreamEvent, RateLimitEvent: ignore for now.
            except Exception as inner:  # noqa: BLE001
                # Never let a persistence bug abort the run — log and continue.
                logger.exception("[%s] failed to persist event", run_label)
                seq = _persist_event(
                    run_id, seq, "error", {"error": f"persist failed: {inner}"}
                )
    except asyncio.CancelledError:
        logger.info("[%s] cancelled by user", run_label)
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            if run is not None:
                _finalize(
                    db,
                    run,
                    status="cancelled",
                    error="Run cancelled by user.",
                )
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("[%s] query failed", run_label)
        # Extract extra detail from ProcessError if available
        error_detail = f"{type(e).__name__}: {e}"
        for attr in ("stderr", "stdout", "output", "returncode", "cmd"):
            val = getattr(e, attr, None)
            if val:
                error_detail += f"\n{attr}: {val}"
        if stderr_lines:
            error_detail += "\n\n--- CLI stderr ---\n" + "\n".join(stderr_lines[-50:])
        error_detail += f"\n\n{traceback.format_exc()}"
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            if run is not None:
                _finalize(
                    db,
                    run,
                    status="failed",
                    error=error_detail,
                )
        return

    # --- Finalize success ---
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if run is None:
            return
        if total_cost_usd is not None:
            run.cost_usd = total_cost_usd
        _finalize(
            db,
            run,
            status="succeeded",
            summary_md=final_text or "*(no final text from agent)*",
        )
        logger.info(
            "[%s] done: %s events, cost=%s",
            run_label,
            seq,
            f"${total_cost_usd:.4f}" if total_cost_usd is not None else "?",
        )


# ------------------------------------------------------------------
# Persistence helpers
# ------------------------------------------------------------------


def _persist_block(run_id: int, seq: int, block) -> int:
    """Translate an Assistant content block into a RunEvent."""
    from claude_agent_sdk import TextBlock, ThinkingBlock, ToolResultBlock, ToolUseBlock

    if isinstance(block, TextBlock):
        return _persist_event(run_id, seq, "text", {"text": block.text})
    if isinstance(block, ToolUseBlock):
        return _persist_event(
            run_id,
            seq,
            "tool_use",
            {
                "tool": block.name,
                "input": _redact(block.input),
                "tool_use_id": block.id,
            },
            increment_tool_count=True,
        )
    if isinstance(block, ToolResultBlock):
        # The SDK surfaces tool results back on UserMessage, not Assistant,
        # but defend against it appearing here anyway.
        content = block.content if isinstance(block.content, str) else str(block.content)
        return _persist_event(
            run_id,
            seq,
            "tool_result",
            {"content": content[:4000], "is_error": bool(block.is_error)},
        )
    if isinstance(block, ThinkingBlock):
        return _persist_event(run_id, seq, "thinking", {"text": "(thinking)"})
    return _persist_event(run_id, seq, "unknown", {"repr": repr(block)[:500]})


def _persist_event(
    run_id: int,
    seq: int,
    kind: str,
    payload: dict,
    *,
    increment_tool_count: bool = False,
) -> int:
    """Insert one RunEvent and optionally bump the parent Run's tool counter."""
    new_seq = seq + 1
    with SessionLocal() as db:
        db.add(RunEvent(run_id=run_id, seq=new_seq, kind=kind, payload=payload))
        if increment_tool_count:
            run = db.get(Run, run_id)
            if run is not None:
                run.tool_call_count = (run.tool_call_count or 0) + 1
        db.commit()
    return new_seq


_SECRET_KEYS = {"client_secret", "password", "token", "authorization", "api_key"}


def _redact(data):
    """Scrub obvious secrets from a tool_use input dict before persisting."""
    if isinstance(data, dict):
        return {k: ("***" if k.lower() in _SECRET_KEYS else _redact(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [_redact(x) for x in data]
    if isinstance(data, str) and len(data) > 1500:
        return data[:1500] + f" …(+{len(data) - 1500} chars)"
    return data


def _finalize(
    db: Session,
    run: Run,
    *,
    status: str,
    summary_md: str = "",
    error: str = "",
) -> None:
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    if summary_md:
        run.summary_md = summary_md
    if error:
        run.error_message = error
    db.commit()


def _mark_failed(run_id: int, error: str) -> None:
    """Synchronous failure path used when the SDK can't even be imported."""
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if run is None:
            return
        _finalize(db, run, status="failed", error=error)
