"""Synthetic demo dataset. Deterministic given SEED_RANDOM_SEED."""
from __future__ import annotations

import logging
import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.connectors.synthetic import CITIES
from app.models import Activity, ListMembership, Prospect, ProspectList
from app.services import enrich, rescore

log = logging.getLogger("prospect-lens.seed")

FIRST = ["Ava", "Liam", "Sophia", "Noah", "Isabella", "Ethan", "Mia", "Lucas", "Amelia", "Mason", "Harper", "Logan",
         "Evelyn", "James", "Abigail", "Benjamin", "Emily", "Jacob", "Elizabeth", "Michael", "Sofia", "Daniel",
         "Avery", "Henry", "Ella", "Jackson", "Scarlett", "Sebastian", "Grace", "Aiden", "Chloe", "Matthew",
         "Victoria", "Samuel", "Riley", "David", "Aria", "Joseph", "Lily", "Carter", "Priya", "Wei", "Diego",
         "Fatima", "Kenji", "Amara", "Mateo", "Leila", "Omar", "Ingrid", "Rafael", "Nadia", "Tomas", "Yuki"]
LAST = ["Anderson", "Bennett", "Castillo", "Delgado", "Ellison", "Foster", "Gallagher", "Hayashi", "Iyer", "Jensen",
        "Kowalski", "Lindqvist", "Moreno", "Nakamura", "O'Brien", "Patel", "Quinn", "Rosenberg", "Sato", "Thornton",
        "Underwood", "Vasquez", "Whitaker", "Xu", "Yamamoto", "Zimmerman", "Abernathy", "Blackwood", "Calloway",
        "Draper", "Everhart", "Fairbanks", "Goldstein", "Holloway", "Ingram", "Jefferson", "Kingsley", "Lockhart",
        "Montgomery", "Northrup", "Okafor", "Pemberton", "Radcliffe", "Sinclair", "Talbot", "Vanderbilt"]
REPS = ["Jordan Lee", "Sam Rivera", "Taylor Kim", "Morgan Blake"]


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(func.count(Prospect.id))):
        return
    log.info("Seeding %d synthetic prospects…", settings.SEED_COUNT)
    r = random.Random(settings.SEED_RANDOM_SEED)
    seen: set[tuple[str, str]] = set()
    prospects: list[Prospect] = []
    while len(prospects) < settings.SEED_COUNT:
        fn, ln = r.choice(FIRST), r.choice(LAST)
        if (fn, ln) in seen:
            continue
        seen.add((fn, ln))
        city, state, zipc, _, _ = r.choice(CITIES)
        p = Prospect(
            first_name=fn, last_name=ln,
            email=f"{fn.lower()}.{ln.lower().replace(chr(39), '')}@example.com",
            city=city, state=state, zip=zipc, source="seed",
            owner=r.choice(REPS) if r.random() < 0.6 else None,
            stage=r.choices(["new", "researching", "contacted", "meeting", "client", "lost"], [50, 18, 16, 8, 5, 3])[0],
            tags=r.sample(["referral", "event", "webinar", "past-client", "linkedin"], k=r.choice([0, 0, 1, 1, 2])),
        )
        db.add(p)
        prospects.append(p)
    db.flush()
    for p in prospects:
        enrich(db, p, live=False)
        rescore(db, p)
        if p.stage in {"contacted", "meeting", "client"}:
            db.add(Activity(prospect_id=p.id, kind=r.choice(["call", "email", "meeting"]),
                            body=r.choice(["Intro call — interested in a second-opinion review.",
                                           "Sent market update; asked about timing.",
                                           "Met at client appreciation event.",
                                           "Left voicemail, follow up next week."]), author=p.owner))
    # Starter lists
    lists = [
        ProspectList(name="Q4 liquidity events", description="Recent sales, exits and upcoming lockups", persona="wealth_manager"),
        ProspectList(name="Move-up sellers — Austin", description="High-equity, 6–12yr tenure in 78746", persona="realtor"),
        ProspectList(name="New business owners", description="Entities formed in the last 12 months", persona="financial_planner"),
    ]
    db.add_all(lists)
    db.flush()
    for p in prospects:
        s = p.score
        if not s:
            continue
        if any(t["key"] in {"insider_sale", "business_exit", "lockup_expiry"} for t in s.triggers) and s.wealth_manager_score >= 50:
            db.add(ListMembership(list_id=lists[0].id, prospect_id=p.id))
        if p.city == "Austin" and s.realtor_score >= 45:
            db.add(ListMembership(list_id=lists[1].id, prospect_id=p.id))
        if any(t["key"] == "new_business" for t in s.triggers):
            db.add(ListMembership(list_id=lists[2].id, prospect_id=p.id))
    db.commit()
    log.info("Seed complete.")
