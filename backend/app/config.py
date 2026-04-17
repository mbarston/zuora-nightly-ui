"""
Settings loaded from environment + .env.

All secrets (master encryption key, Google OAuth creds, Anthropic API key)
live here and are read by the rest of the app via `settings`.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[2]  # repo root
DATA_DIR = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- app ---
    APP_NAME: str = "Zuora SE Demo Data Agent"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    # In dev this can be "http://localhost:8000"; in prod, the real URL.
    # Used to build the Google OAuth redirect URI.
    APP_BASE_URL: str = "http://localhost:8000"

    # Random, long string used to sign session cookies. ROTATE = log everyone out.
    SESSION_SECRET: str = "change-me-to-a-long-random-string"

    # --- db ---
    # SQLite file lives under data/. Easy to back up; swap to Postgres later.
    DATABASE_URL: str = f"sqlite:///{DATA_DIR / 'app.db'}"

    # --- crypto ---
    # Fernet key (44 chars, base64-urlsafe). Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # If this rotates, all stored Zuora secrets become unreadable.
    MASTER_ENCRYPTION_KEY: str = ""

    # --- auth ---
    # Gate login to a specific email domain. Empty string = allow any Google account.
    ALLOWED_EMAIL_DOMAIN: str = "zuora.com"

    # Google OAuth credentials from console.cloud.google.com → Credentials.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # Bypass Google OAuth entirely for local development. When true, POST /auth/dev-login
    # creates or reuses a dev user. NEVER enable this in production.
    DEV_AUTH_BYPASS: bool = False

    # --- Claude (wired in Phase 2) ---
    ANTHROPIC_API_KEY: str = ""

    # Model used by the Claude Agent SDK for both nightly/backfill runs and
    # the chat assistant. Accepts SDK aliases ("sonnet", "opus", "haiku") or
    # full model IDs. Default is Sonnet for cost stability; override per-env
    # via CLAUDE_MODEL if a specific deployment needs Opus.
    CLAUDE_MODEL: str = "sonnet"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    s = Settings()
    # In Docker the DATABASE_URL points at /data/app.db (persistent volume).
    # Make sure the parent directory exists there too.
    db_path = s.DATABASE_URL.replace("sqlite:///", "")
    if db_path.startswith("/"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
