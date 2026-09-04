from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ListMembership, Prospect, ProspectList
from app.schemas import ListIn, ListOut, MembersIn, Page, ProspectRow

router = APIRouter(prefix="/api/lists", tags=["lists"])


def _out(db: Session, l: ProspectList) -> ListOut:
    n = db.scalar(select(func.count(ListMembership.id)).where(ListMembership.list_id == l.id)) or 0
    return ListOut(id=l.id, name=l.name, description=l.description, persona=l.persona,
                   created_at=l.created_at, member_count=n)


@router.get("", response_model=list[ListOut])
def list_lists(db: Session = Depends(get_db)):
    return [_out(db, l) for l in db.scalars(select(ProspectList).order_by(ProspectList.created_at))]


@router.post("", response_model=ListOut, status_code=201)
def create_list(body: ListIn, db: Session = Depends(get_db)):
    if db.scalar(select(ProspectList).where(ProspectList.name == body.name)):
        raise HTTPException(409, "A list with that name already exists")
    l = ProspectList(**body.model_dump())
    db.add(l)
    db.commit()
    return _out(db, l)


def _load(db: Session, list_id: int) -> ProspectList:
    l = db.get(ProspectList, list_id)
    if not l:
        raise HTTPException(404, "List not found")
    return l


@router.get("/{list_id}", response_model=ListOut)
def get_list(list_id: int, db: Session = Depends(get_db)):
    return _out(db, _load(db, list_id))


@router.delete("/{list_id}", status_code=204)
def delete_list(list_id: int, db: Session = Depends(get_db)):
    db.delete(_load(db, list_id))
    db.commit()


@router.get("/{list_id}/members", response_model=Page)
def members(list_id: int, db: Session = Depends(get_db)):
    l = _load(db, list_id)
    rows = db.scalars(
        select(Prospect).join(ListMembership).where(ListMembership.list_id == l.id, Prospect.suppressed.is_(False))
        .order_by(ListMembership.added_at.desc())
    ).all()
    return Page(items=[ProspectRow.model_validate(r) for r in rows], total=len(rows), page=1, page_size=len(rows) or 1)


@router.post("/{list_id}/members", response_model=ListOut)
def add_members(list_id: int, body: MembersIn, db: Session = Depends(get_db)):
    l = _load(db, list_id)
    existing = set(db.scalars(select(ListMembership.prospect_id).where(ListMembership.list_id == l.id)))
    for pid in body.prospect_ids:
        if pid in existing or not db.get(Prospect, pid):
            continue
        db.add(ListMembership(list_id=l.id, prospect_id=pid))
    db.commit()
    return _out(db, l)


@router.delete("/{list_id}/members/{prospect_id}", response_model=ListOut)
def remove_member(list_id: int, prospect_id: int, db: Session = Depends(get_db)):
    l = _load(db, list_id)
    m = db.scalar(select(ListMembership).where(ListMembership.list_id == l.id, ListMembership.prospect_id == prospect_id))
    if m:
        db.delete(m)
        db.commit()
    return _out(db, l)


@router.get("/{list_id}/export.csv")
def export_csv(list_id: int, db: Session = Depends(get_db)):
    """Export honours the suppression registry — opted-out people are never exported."""
    l = _load(db, list_id)
    rows = db.scalars(
        select(Prospect).join(ListMembership).where(ListMembership.list_id == l.id, Prospect.suppressed.is_(False))
    ).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["first_name", "last_name", "email", "city", "state", "zip", "employer", "title", "wealth_tier",
                "net_worth_p50", "investable_assets", "realtor_score", "wealth_manager_score",
                "financial_planner_score", "triggers", "next_best_action"])
    for p in rows:
        s = p.score
        nba = (s.explanation.get("personas", {}).get(l.persona, {}).get("next_best_action", "") if s else "")
        w.writerow([p.first_name, p.last_name, p.email, p.city, p.state, p.zip, p.employer, p.title,
                    s.wealth_tier if s else "", int(s.net_worth_p50) if s else "", int(s.investable_assets) if s else "",
                    s.realtor_score if s else "", s.wealth_manager_score if s else "", s.financial_planner_score if s else "",
                    "; ".join(t["label"] for t in (s.triggers if s else [])), nba])
    buf.seek(0)
    fname = l.name.lower().replace(" ", "-") + ".csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})
