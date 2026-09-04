"""
Prospect Lens — FastAPI entry point.

  uvicorn app.main:app --reload --port 8787   (from backend/)

JSON API under /api/*. The React SPA (frontend/dist) is served from / with an
SPA fallback when it has been built; otherwise use the Vite dev server.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import SessionLocal, init_db
from app.routers import lists, meta, prospects
from app.seed import seed_if_empty

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("prospect-lens")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.SEED_ON_STARTUP:
        with SessionLocal() as db:
            seed_if_empty(db)
    if settings.LIVE_CONNECTORS:
        log.warning("LIVE_CONNECTORS enabled — enrichment will call SEC EDGAR / FEC / OpenCorporates.")
    yield


app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)
app.include_router(prospects.router)
app.include_router(lists.router)
app.include_router(meta.router)

if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    index = FRONTEND_DIST / "index.html"
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    candidate = FRONTEND_DIST / path
    if path and candidate.is_file():
        return FileResponse(candidate)
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "Frontend not built. Run `npm run build` in frontend/ or use the Vite dev server."},
                        status_code=404)
