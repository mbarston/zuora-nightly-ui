from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Activity, ListMembership, Prospect, ProspectList, ScoreSnapshot
from app.schemas import (
    ActivityIn, ActivityOut, Page, ProspectDetail, ProspectIn, ProspectPatch, ProspectRow,
)
from app.scoring.personas import PERSONAS
from app.services import enrich, is_suppressed, rescore

router = APIRouter(prefix="/api/prospects", tags=["prospects"])

STAGES = ["new", "researching", "contacted", "meeting", "client", "lost"]
SORTABLE = {
    "realtor": ScoreSnapshot.realtor_score,
    "wealth_manager": ScoreSnapshot.wealth_manager_score,
    "financial_planner": ScoreSnapshot.financial_planner_score,
    "net_worth": ScoreSnapshot.net_worth_p50,
    "investable": ScoreSnapshot.investable_assets,
    "name": Prospect.last_name,
    "updated": Prospect.updated_at,
}


@router.get("", response_model=Page)
def list_prospects(
    db: Session = Depends(get_db),
    q: str | None = None,
    persona: str = Query("wealth_manager", pattern="^(realtor|wealth_manager|financial_planner)$"),
    min_score: int = Query(0, ge=0, le=100),
    tier: str | None = None,
    state: str | None = None,
    stage: str | None = None,
    owner: str | None = None,
    trigger: str | None = None,
    hot_only: bool = False,
    include_suppressed: bool = False,
    sort: str | None = None,
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    stmt = select(Prospect).outerjoin(ScoreSnapshot).options(selectinload(Prospect.score))
    if not include_suppressed:
        stmt = stmt.where(Prospect.suppressed.is_(False))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            (Prospect.first_name + " " + Prospect.last_name).ilike(like),
            Prospect.email.ilike(like), Prospect.employer.ilike(like), Prospect.city.ilike(like),
            Prospect.title.ilike(like),
        ))
    score_col = SORTABLE[persona]
    if min_score:
        stmt = stmt.where(score_col >= min_score)
    if tier:
        stmt = stmt.where(ScoreSnapshot.wealth_tier.in_(tier.split(",")))
    if state:
        stmt = stmt.where(Prospect.state == state.upper())
    if stage:
        stmt = stmt.where(Prospect.stage.in_(stage.split(",")))
    if owner:
        stmt = stmt.where(Prospect.owner == owner)
    if trigger:
        stmt = stmt.where(cast(ScoreSnapshot.triggers, String).like(f'%"key": "{trigger}%'))
    if hot_only:
        stmt = stmt.where(cast(ScoreSnapshot.triggers, String).like('%"urgency": "hot"%'))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sort_col = SORTABLE.get(sort or persona, score_col)
    stmt = stmt.order_by(sort_col.asc().nulls_last() if order == "asc" else sort_col.desc().nulls_last(), Prospect.id)
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[ProspectRow.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.post("", response_model=ProspectRow, status_code=201)
def create_prospect(body: ProspectIn, db: Session = Depends(get_db), enrich_now: bool = True):
    p = Prospect(**body.model_dump(), source="manual")
    db.add(p)
    db.flush()
    p.suppressed = is_suppressed(db, p)
    if enrich_now:
        enrich(db, p)
    rescore(db, p)
    db.commit()
    db.refresh(p)
    return p


@router.post("/import", status_code=201)
async def import_csv(file: UploadFile, db: Session = Depends(get_db), enrich_now: bool = True):
    """CSV columns (header names, any order, case-insensitive):
    first_name,last_name,email,phone,street,city,state,zip,age_band,employer,title,owner,tags"""
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    created, skipped, errors = 0, 0, []
    for i, row in enumerate(reader, start=2):
        r = {(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in row.items()}
        if "name" in r and not r.get("first_name"):
            parts = r["name"].split(" ", 1)
            r["first_name"], r["last_name"] = parts[0], parts[1] if len(parts) > 1 else ""
        if not r.get("first_name") or not r.get("last_name"):
            errors.append(f"row {i}: missing name")
            continue
        if r.get("email") and db.scalar(select(Prospect).where(Prospect.email == r["email"])):
            skipped += 1
            continue
        p = Prospect(
            first_name=r["first_name"], last_name=r["last_name"], email=r.get("email") or None,
            phone=r.get("phone") or None, street=r.get("street") or None, city=r.get("city") or None,
            state=(r.get("state") or None) and r["state"][:2].upper(), zip=r.get("zip") or None,
            age_band=r.get("age_band") or None, employer=r.get("employer") or None, title=r.get("title") or None,
            owner=r.get("owner") or None, tags=[t.strip() for t in r.get("tags", "").split(";") if t.strip()],
            source="import",
        )
        db.add(p)
        db.flush()
        p.suppressed = is_suppressed(db, p)
        if enrich_now:
            enrich(db, p)
        rescore(db, p)
        created += 1
    db.commit()
    return {"created": created, "skipped_duplicates": skipped, "errors": errors}


def _load(db: Session, prospect_id: int) -> Prospect:
    p = db.get(Prospect, prospect_id)
    if not p:
        raise HTTPException(404, "Prospect not found")
    return p


@router.get("/{prospect_id}", response_model=ProspectDetail)
def get_prospect(prospect_id: int, db: Session = Depends(get_db)):
    p = _load(db, prospect_id)
    lists = db.execute(
        select(ProspectList.id, ProspectList.name).join(ListMembership).where(ListMembership.prospect_id == p.id)
    ).all()
    return ProspectDetail(
        **ProspectRow.model_validate(p).model_dump(),
        phone=p.phone, street=p.street, created_at=p.created_at,
        signals=[s for s in p.signals], activities=[a for a in p.activities],
        explanation=(p.score.explanation if p.score else {}),
        lists=[{"id": i, "name": n} for i, n in lists],
    )


@router.patch("/{prospect_id}", response_model=ProspectRow)
def patch_prospect(prospect_id: int, body: ProspectPatch, db: Session = Depends(get_db)):
    p = _load(db, prospect_id)
    if body.stage is not None:
        if body.stage not in STAGES:
            raise HTTPException(422, f"stage must be one of {STAGES}")
        if body.stage != p.stage:
            db.add(Activity(prospect_id=p.id, kind="stage", body=f"Stage changed {p.stage} → {body.stage}"))
        p.stage = body.stage
    for f in ("owner", "tags", "phone", "email"):
        v = getattr(body, f)
        if v is not None:
            setattr(p, f, v)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{prospect_id}", status_code=204)
def delete_prospect(prospect_id: int, db: Session = Depends(get_db)):
    db.delete(_load(db, prospect_id))
    db.commit()


@router.post("/{prospect_id}/enrich", response_model=ProspectDetail)
def enrich_prospect(prospect_id: int, db: Session = Depends(get_db)):
    p = _load(db, prospect_id)
    added = enrich(db, p)
    rescore(db, p)
    db.add(Activity(prospect_id=p.id, kind="system", body=f"Enrichment run: {added} new signal(s)"))
    db.commit()
    return get_prospect(prospect_id, db)


@router.post("/{prospect_id}/rescore", response_model=ProspectDetail)
def rescore_prospect(prospect_id: int, db: Session = Depends(get_db)):
    p = _load(db, prospect_id)
    rescore(db, p)
    db.commit()
    return get_prospect(prospect_id, db)


@router.post("/{prospect_id}/activities", response_model=ActivityOut, status_code=201)
def add_activity(prospect_id: int, body: ActivityIn, db: Session = Depends(get_db)):
    p = _load(db, prospect_id)
    a = Activity(prospect_id=p.id, **body.model_dump())
    db.add(a)
    if p.stage == "new" and body.kind in {"call", "email", "meeting"}:
        p.stage = "contacted"
    db.commit()
    db.refresh(a)
    return a


@router.get("/meta/personas")
def personas():
    return PERSONAS
