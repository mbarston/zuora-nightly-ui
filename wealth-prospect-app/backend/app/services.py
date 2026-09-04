"""Enrichment + scoring orchestration shared by routers and the seeder."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import ProspectIdentity
from app.connectors.registry import run_all
from app.models import Prospect, ScoreSnapshot, Signal, Suppression, utcnow
from app.scoring.engine import score_prospect


def identity_of(p: Prospect) -> ProspectIdentity:
    return ProspectIdentity(
        id=p.id, first_name=p.first_name, last_name=p.last_name, email=p.email, street=p.street,
        city=p.city, state=p.state, zip=p.zip, employer=p.employer, title=p.title, age_band=p.age_band,
    )


def enrich(db: Session, p: Prospect, live: bool | None = None) -> int:
    """Run all connectors, upsert signals (dedupe by key), return number added."""
    existing = {s.dedupe_key for s in p.signals if s.dedupe_key}
    added = 0
    for _key, drafts in run_all(identity_of(p), live=live).items():
        for d in drafts:
            if d.dedupe_key and d.dedupe_key in existing:
                continue
            db.add(Signal(
                prospect_id=p.id, kind=d.kind, source=d.source, source_ref=d.source_ref,
                confidence=d.confidence, observed_at=d.observed_at or utcnow(), summary=d.summary,
                data=d.data, dedupe_key=d.dedupe_key,
            ))
            if d.dedupe_key:
                existing.add(d.dedupe_key)
            added += 1
    p.last_enriched_at = utcnow()
    db.flush()
    _backfill_identity(db, p)
    return added


def _backfill_identity(db: Session, p: Prospect) -> None:
    db.refresh(p)
    for s in p.signals:
        if s.kind == "employment.title":
            p.employer = p.employer or s.data.get("employer")
            p.title = p.title or s.data.get("title")
        elif s.kind == "demographic.household":
            p.age_band = p.age_band or s.data.get("age_band")
        elif s.kind == "property.owned" and s.data.get("is_primary"):
            p.street = p.street or s.data.get("address")
            p.city = p.city or s.data.get("city")
            p.state = p.state or s.data.get("state")
            p.zip = p.zip or s.data.get("zip")


def rescore(db: Session, p: Prospect, now: datetime | None = None) -> ScoreSnapshot:
    db.refresh(p)
    result = score_prospect(p.signals, now=now)
    w = result.wealth
    snap = p.score or ScoreSnapshot(prospect_id=p.id)
    snap.computed_at = utcnow()
    snap.net_worth_p10 = w.net_worth_p10
    snap.net_worth_p50 = w.net_worth_p50
    snap.net_worth_p90 = w.net_worth_p90
    snap.investable_assets = w.investable_assets
    snap.income_estimate = w.income_estimate
    snap.real_estate_equity = w.real_estate_equity
    snap.business_equity = w.business_equity
    snap.public_equity = w.public_equity
    snap.financial_assets = w.financial_assets
    snap.confidence = w.confidence
    snap.wealth_tier = w.wealth_tier
    snap.realtor_score = result.personas["realtor"].score
    snap.wealth_manager_score = result.personas["wealth_manager"].score
    snap.financial_planner_score = result.personas["financial_planner"].score
    snap.triggers = result.triggers
    snap.explanation = result.to_explanation()
    if p.score is None:
        db.add(snap)
        p.score = snap
    db.flush()
    return snap


def is_suppressed(db: Session, p: Prospect) -> bool:
    q = select(Suppression)
    for s in db.scalars(q):
        if s.email and p.email and s.email.lower() == p.email.lower():
            return True
        if s.full_name and s.full_name.lower() == p.full_name.lower() and (not s.zip or s.zip == p.zip):
            return True
    return False


def apply_suppressions(db: Session) -> int:
    """Re-evaluate every prospect against the suppression registry. Returns count suppressed."""
    n = 0
    for p in db.scalars(select(Prospect)):
        flag = is_suppressed(db, p)
        if flag != p.suppressed:
            p.suppressed = flag
        n += int(flag)
    db.flush()
    return n
