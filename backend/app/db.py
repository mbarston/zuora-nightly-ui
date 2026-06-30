"""
SQLAlchemy engine + session factory, plus a simple create_all bootstrap.

We're not using Alembic in Phase 1 because the schema is tiny and churning
fast. When it stabilises (Phase 3), swap create_all() for real migrations.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


# check_same_thread=False is required for SQLite + FastAPI (multiple requests
# hit the same connection from different threadpool workers).
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _ensure_columns() -> None:
    """Add any columns defined in models but missing from the live DB.

    SQLAlchemy's create_all() won't ALTER existing tables, so new columns
    added to models.py need a manual migration. This helper introspects
    the DB and issues ALTER TABLE … ADD COLUMN for anything missing.
    Safe to call repeatedly — it's a no-op once the columns exist.
    """
    insp = inspect(engine)
    meta = Base.metadata
    with engine.begin() as conn:
        for table_name, table in meta.tables.items():
            if not insp.has_table(table_name):
                continue  # create_all will handle brand-new tables
            existing = {c["name"] for c in insp.get_columns(table_name)}
            for col in table.columns:
                if col.name not in existing:
                    # Build a minimal ALTER TABLE so existing rows backfill to a
                    # valid value. Honor a scalar python-side default (str/num/
                    # bool) when present — otherwise fall back to '{}', which is
                    # the right shape for our JSON columns (default=dict/list).
                    col_type = col.type.compile(engine.dialect)
                    default = "'{}'"
                    col_default = col.default
                    if col_default is not None and getattr(col_default, "is_scalar", False):
                        arg = col_default.arg
                        if isinstance(arg, bool):
                            default = "1" if arg else "0"
                        elif isinstance(arg, (int, float)):
                            default = str(arg)
                        elif isinstance(arg, str):
                            default = "'" + arg.replace("'", "''") + "'"
                    stmt = f'ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type} DEFAULT {default}'
                    conn.execute(text(stmt))


def init_db() -> None:
    """Create tables if they don't exist. Called at app startup."""
    # Import models so they register with Base.metadata before create_all runs.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
