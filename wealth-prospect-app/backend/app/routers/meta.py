"""Stats, data-source registry, compliance."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.connectors.registry import CONNECTORS
from app.db import get_db
from app.models import Prospect, ScoreSnapshot, Signal, Suppression
from app.schemas import SuppressionIn, SuppressionOut
from app.scoring.signals import SIGNAL_KINDS
from app.services import apply_suppressions

router = APIRouter(prefix="/api", tags=["meta"])

PERMISSIBLE_USE = (
    "Prospect Lens produces marketing prospecting insights derived from public records and first-party data. "
    "It is not a consumer reporting agency and its outputs are not consumer reports under the Fair Credit "
    "Reporting Act (FCRA). Outputs must not be used to determine eligibility for credit, insurance, employment, "
    "housing, or any other purpose covered by FCRA, the Fair Housing Act, or ECOA. Political-contribution data "
    "must not be used to solicit contributions. Honour every opt-out and deletion request within the statutory window."
)


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    total = db.scalar(select(func.count(Prospect.id)).where(Prospect.suppressed.is_(False))) or 0
    snaps = db.scalars(select(ScoreSnapshot).join(Prospect).where(Prospect.suppressed.is_(False))).all()
    tiers = Counter(s.wealth_tier for s in snaps)
    hot = [s for s in snaps if any(t["urgency"] == "hot" for t in s.triggers)]
    trig = Counter(t["key"] for s in snaps for t in s.triggers)
    week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    new_triggers = sum(1 for s in snaps for t in s.triggers if t["date"] >= week_ago)

    def dist(field: str) -> list[int]:
        buckets = [0] * 10
        for s in snaps:
            v = getattr(s, field)
            buckets[min(9, v // 10)] += 1
        return buckets

    total_nw = sum(s.net_worth_p50 for s in snaps)
    stages = Counter(p.stage for p in db.scalars(select(Prospect).where(Prospect.suppressed.is_(False))))
    sources = Counter(s.source for s in db.scalars(select(Signal)))
    return {
        "prospects": total,
        "suppressed": db.scalar(select(func.count(Prospect.id)).where(Prospect.suppressed.is_(True))) or 0,
        "hot_prospects": len(hot),
        "new_triggers_7d": new_triggers,
        "total_net_worth_p50": total_nw,
        "avg_confidence": round(sum(s.confidence for s in snaps) / len(snaps), 3) if snaps else 0,
        "tiers": {k: tiers.get(k, 0) for k in ["ultra", "vhnw", "hnw", "affluent", "mass"]},
        "triggers": trig.most_common(12),
        "score_distribution": {
            "realtor": dist("realtor_score"),
            "wealth_manager": dist("wealth_manager_score"),
            "financial_planner": dist("financial_planner_score"),
        },
        "stages": dict(stages),
        "signals_by_source": dict(sources),
        "signals_total": sum(sources.values()),
    }


@router.get("/sources")
def sources(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Signal.source, func.count(Signal.id)).group_by(Signal.source)).all())
    latest = dict(db.execute(select(Signal.source, func.max(Signal.observed_at)).group_by(Signal.source)).all())
    out = []
    for key, c in CONNECTORS.items():
        m = c.meta
        out.append({
            **m.__dict__, "mode": c.mode, "supports_live": c.supports_live,
            "signal_count": counts.get(key, 0),
            "last_observed": latest.get(key).isoformat() if latest.get(key) else None,
            "signal_labels": [SIGNAL_KINDS[k][1] for k in m.signal_kinds if k in SIGNAL_KINDS],
        })
    return {"live_connectors": settings.LIVE_CONNECTORS, "sources": out}


@router.get("/compliance")
def compliance(db: Session = Depends(get_db)):
    rows = db.scalars(select(Suppression).order_by(Suppression.created_at.desc())).all()
    return {"permissible_use": PERMISSIBLE_USE, "suppressions": [SuppressionOut.model_validate(r) for r in rows]}


@router.post("/compliance/suppressions", response_model=SuppressionOut, status_code=201)
def add_suppression(body: SuppressionIn, db: Session = Depends(get_db)):
    if not body.email and not body.full_name:
        raise HTTPException(422, "Provide an email or a full name")
    s = Suppression(**body.model_dump())
    db.add(s)
    db.flush()
    apply_suppressions(db)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/compliance/suppressions/{sid}", status_code=204)
def remove_suppression(sid: int, db: Session = Depends(get_db)):
    s = db.get(Suppression, sid)
    if not s:
        raise HTTPException(404, "Not found")
    db.delete(s)
    db.flush()
    apply_suppressions(db)
    db.commit()


@router.get("/health")
def health():
    return {"ok": True, "app": settings.APP_NAME, "live_connectors": settings.LIVE_CONNECTORS}
