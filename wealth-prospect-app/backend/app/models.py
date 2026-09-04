"""
Data model.

The core idea: a Prospect is a person (or household). Everything we know about
them is stored as a *Signal* — one observed fact from one source, with
provenance and a confidence. Scores are derived from signals and cached on a
ScoreSnapshot so the list view is fast, but the explanation for every score
can always be traced back to the individual signals it came from.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Prospect(Base):
    __tablename__ = "prospects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    street: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    zip: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    age_band: Mapped[str | None] = mapped_column(String(10), nullable=True)  # e.g. "45-54"
    employer: Mapped[str | None] = mapped_column(String(160), nullable=True)
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="manual")  # manual | import | seed
    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)  # assigned rep
    stage: Mapped[str] = mapped_column(String(30), default="new")  # new|researching|contacted|meeting|client|lost
    tags: Mapped[list] = mapped_column(JSON, default=list)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    signals: Mapped[list[Signal]] = relationship(
        back_populates="prospect", cascade="all, delete-orphan", order_by="Signal.observed_at.desc()"
    )
    score: Mapped[ScoreSnapshot | None] = relationship(
        back_populates="prospect", uselist=False, cascade="all, delete-orphan"
    )
    activities: Mapped[list[Activity]] = relationship(
        back_populates="prospect", cascade="all, delete-orphan", order_by="Activity.created_at.desc()"
    )
    memberships: Mapped[list[ListMembership]] = relationship(
        back_populates="prospect", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Signal(Base):
    """One observed fact about a prospect from one source."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(60), index=True)  # see scoring/signals.py
    source: Mapped[str] = mapped_column(String(60), index=True)  # connector key
    source_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)  # URL / doc id
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    summary: Mapped[str] = mapped_column(String(300))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

    prospect: Mapped[Prospect] = relationship(back_populates="signals")

    __table_args__ = (UniqueConstraint("prospect_id", "dedupe_key", name="uq_signal_dedupe"),)


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prospect_id: Mapped[int] = mapped_column(
        ForeignKey("prospects.id", ondelete="CASCADE"), unique=True, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    net_worth_p10: Mapped[float] = mapped_column(Float, default=0)
    net_worth_p50: Mapped[float] = mapped_column(Float, default=0, index=True)
    net_worth_p90: Mapped[float] = mapped_column(Float, default=0)
    investable_assets: Mapped[float] = mapped_column(Float, default=0, index=True)
    income_estimate: Mapped[float] = mapped_column(Float, default=0)
    real_estate_equity: Mapped[float] = mapped_column(Float, default=0)
    business_equity: Mapped[float] = mapped_column(Float, default=0)
    public_equity: Mapped[float] = mapped_column(Float, default=0)
    financial_assets: Mapped[float] = mapped_column(Float, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0)  # 0..1 data coverage/quality
    realtor_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    wealth_manager_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    financial_planner_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    wealth_tier: Mapped[str] = mapped_column(String(20), default="mass", index=True)
    triggers: Mapped[list] = mapped_column(JSON, default=list)  # active timing triggers
    explanation: Mapped[dict] = mapped_column(JSON, default=dict)  # full factor breakdown

    prospect: Mapped[Prospect] = relationship(back_populates="score")


class ProspectList(Base):
    __tablename__ = "lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    persona: Mapped[str] = mapped_column(String(30), default="wealth_manager")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    memberships: Mapped[list[ListMembership]] = relationship(
        back_populates="list", cascade="all, delete-orphan"
    )


class ListMembership(Base):
    __tablename__ = "list_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("lists.id", ondelete="CASCADE"), index=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    list: Mapped[ProspectList] = relationship(back_populates="memberships")
    prospect: Mapped[Prospect] = relationship(back_populates="memberships")

    __table_args__ = (UniqueConstraint("list_id", "prospect_id", name="uq_list_member"),)


class Activity(Base):
    """Rep notes and contact log. Also the audit trail for stage changes."""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="note")  # note|call|email|meeting|stage|system
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    prospect: Mapped[Prospect] = relationship(back_populates="activities")


class Suppression(Base):
    """Opt-out / do-not-contact registry. Matched by email or name+zip."""

    __tablename__ = "suppressions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    zip: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reason: Mapped[str] = mapped_column(String(60), default="opt_out")  # opt_out|dnc|ccpa_delete|client
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
