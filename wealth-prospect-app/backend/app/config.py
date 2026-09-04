"""Runtime configuration. Everything is overridable via environment variables."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "Prospect Lens")
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'prospects.db'}")
    # When true, connectors call real public APIs (SEC EDGAR, FEC, ProPublica).
    # Default false: connectors return deterministic synthetic signals so the
    # app is fully usable offline and in tests.
    LIVE_CONNECTORS: bool = _bool("LIVE_CONNECTORS", False)
    FEC_API_KEY: str = os.getenv("FEC_API_KEY", "DEMO_KEY")
    SEC_USER_AGENT: str = os.getenv("SEC_USER_AGENT", "ProspectLens dev@example.com")
    SEED_ON_STARTUP: bool = _bool("SEED_ON_STARTUP", True)
    SEED_COUNT: int = int(os.getenv("SEED_COUNT", "240"))
    SEED_RANDOM_SEED: int = int(os.getenv("SEED_RANDOM_SEED", "20260904"))


settings = Settings()
