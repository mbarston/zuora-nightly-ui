"""
FastAPI app factory. Single entry point for `uvicorn app.main:app`.

Phase 5c layout:
  - JSON API under /api/*  (app.routers.api.core)
  - Google OAuth + dev-login under /auth/* (app.auth)
  - The React SPA is served from /. In dev, Vite runs on :5173 and proxies
    /api + /auth to this process. In prod, we build the React app into
    frontend/dist and this process serves the built assets from / with a
    SPA fallback so deep links like /runs/42 resolve to index.html on
    hard reload.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import auth as auth_module
from app.config import settings
from app.crypto import healthcheck as crypto_healthcheck
from app.db import init_db
from app.routers.api import core as api_core
from app.scheduler import start_scheduler, stop_scheduler


logger = logging.getLogger("zuora-se-agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


# Resolve the built React app once at import time. In dev this directory
# won't exist until the first `npm run build`, and that's fine — the Vite
# dev server is the primary way to iterate. The SPA catch-all below returns
# a helpful 404 payload in that case.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    init_db()
    if not crypto_healthcheck():
        logger.warning(
            "Crypto healthcheck failed — MASTER_ENCRYPTION_KEY is missing or invalid. "
            "Tenant creation will fail until you set a valid Fernet key in .env."
        )
    else:
        logger.info("Crypto healthcheck OK.")
    if settings.DEV_AUTH_BYPASS:
        logger.warning(
            "DEV_AUTH_BYPASS is enabled. Anyone who can reach this server can "
            "POST /api/auth/dev-login and become a user. Disable before deploying."
        )
    if not FRONTEND_INDEX.exists():
        logger.warning(
            "frontend/dist/index.html not found. The React SPA will 404 until "
            "you run `cd frontend && npm run build`, or hit the Vite dev server "
            "on port 5173 instead."
        )
    # Recover orphaned runs/backfills left in queued/running by a crash or restart.
    _recover_orphaned_runs()
    try:
        await start_scheduler()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to start scheduler — continuing without it")
    yield
    # --- shutdown ---
    try:
        await stop_scheduler()
    except Exception:  # noqa: BLE001
        logger.exception("Error shutting down scheduler")


def _recover_orphaned_runs() -> None:
    """Mark any queued/running runs or backfills as failed on startup.

    If the server crashed or restarted mid-run, those tasks are gone but the
    DB rows still say 'running'. Clean them up so the tenant isn't permanently
    locked out of new runs.
    """
    from datetime import datetime, timezone
    from app.db import SessionLocal
    from app.models import Run, BackfillJob

    with SessionLocal() as db:
        orphaned_runs = (
            db.query(Run)
            .filter(Run.status.in_(("queued", "running")))
            .all()
        )
        for run in orphaned_runs:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = "Run was interrupted by a server restart."
            logger.warning("Recovered orphaned run-%d (was %s)", run.id, "running")

        orphaned_jobs = (
            db.query(BackfillJob)
            .filter(BackfillJob.status.in_(("queued", "running")))
            .all()
        )
        for job in orphaned_jobs:
            job.status = "failed"
            job.finished_at = datetime.now(timezone.utc)
            job.error_message = "Backfill was interrupted by a server restart."
            logger.warning("Recovered orphaned backfill-%d", job.id)

        if orphaned_runs or orphaned_jobs:
            db.commit()
            logger.info(
                "Recovered %d orphaned run(s) and %d orphaned backfill(s)",
                len(orphaned_runs), len(orphaned_jobs),
            )


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # --- session cookie, signed with SESSION_SECRET ---
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SESSION_SECRET,
        same_site="lax",
        https_only=False,
    )

    # --- routes ---
    # API routes must be registered BEFORE the SPA catch-all below, otherwise
    # the fallback will swallow /api/* requests and return index.html.
    app.include_router(auth_module.router)
    app.include_router(api_core.router)  # JSON API under /api/*

    # --- static assets + SPA fallback ---------------------------------------
    # Vite's production build emits hashed JS/CSS into dist/assets/. We mount
    # that as a subpath so it doesn't collide with our /api routes, then add
    # a catch-all that returns index.html for every other unmatched path so
    # React Router can handle client-side routing on hard reloads.
    if FRONTEND_DIST.exists():
        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.exists():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="assets",
            )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request):
        # Don't intercept API/auth paths — if they didn't match an earlier
        # route it's a real 404 and should look like one.
        if (
            full_path.startswith("api/")
            or full_path.startswith("auth/")
            or full_path.startswith("assets/")
        ):
            raise HTTPException(status_code=404)

        # Serve any static file living directly in dist/ (favicon, robots, etc.).
        if full_path:
            direct = FRONTEND_DIST / full_path
            if direct.is_file() and _safe_within(direct, FRONTEND_DIST):
                return FileResponse(direct)

        if FRONTEND_INDEX.exists():
            return FileResponse(FRONTEND_INDEX)

        # Dev safety net: if the build doesn't exist, tell the user what to do.
        return JSONResponse(
            status_code=404,
            content={
                "detail": (
                    "React build not found. Run `cd frontend && npm run build`, "
                    "or use the Vite dev server at http://localhost:5173"
                )
            },
        )

    # --- exception handlers ---
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error. Check the server log."},
        )

    return app


def _safe_within(candidate: Path, root: Path) -> bool:
    """Guard against path traversal in the SPA fallback."""
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


app = create_app()
