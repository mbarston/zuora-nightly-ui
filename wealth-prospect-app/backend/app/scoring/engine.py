"""
Scoring engine.

Two layers:

1. `estimate_wealth(signals)` — builds a transparent balance sheet from
   signals: real-estate equity, private business equity, public equity,
   liquid financial assets, and an income estimate. Produces a P10/P50/P90
   net-worth range whose width shrinks as data coverage improves.

2. `score_persona(persona, ...)` — turns the balance sheet + timing signals
   into a 0-100 propensity score for a specific professional (realtor,
   wealth manager, financial planner). Every point is attributed to a named
   factor with the signal ids that produced it.

The whole thing is deterministic and dependency-free so it is trivial to
unit test and to explain to a customer ("why is this person a 78?").
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from app.scoring.personas import PERSONAS
from app.scoring.signals import (
    AGE_SAVINGS_MULTIPLIER,
    CATEGORIES,
    INDUSTRY_COMP_FACTOR,
    INDUSTRY_REVENUE_MULTIPLE,
    SENIORITY_COMP,
    SIGNAL_KINDS,
)


# --------------------------------------------------------------------------- #
# Input abstraction — works with ORM Signal rows or plain dicts (tests).
# --------------------------------------------------------------------------- #
@dataclass
class Sig:
    id: int | None
    kind: str
    source: str
    confidence: float
    observed_at: datetime
    data: dict

    @classmethod
    def from_any(cls, s) -> "Sig":  # noqa: ANN001
        if isinstance(s, dict):
            return cls(
                id=s.get("id"),
                kind=s["kind"],
                source=s.get("source", "unknown"),
                confidence=float(s.get("confidence", 0.7)),
                observed_at=_dt(s.get("observed_at")) or datetime.utcnow(),
                data=s.get("data") or {},
            )
        return cls(
            id=s.id,
            kind=s.kind,
            source=s.source,
            confidence=float(s.confidence),
            observed_at=s.observed_at,
            data=s.data or {},
        )


def _dt(v) -> datetime | None:  # noqa: ANN001
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v)[:19])
    except ValueError:
        return None


def _num(v, default: float = 0.0) -> float:  # noqa: ANN001
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Output types
# --------------------------------------------------------------------------- #
@dataclass
class Factor:
    name: str
    label: str
    value: float  # dollars for wealth factors, points for propensity factors
    detail: str
    signal_ids: list[int] = field(default_factory=list)


@dataclass
class WealthEstimate:
    income_estimate: float = 0.0
    real_estate_equity: float = 0.0
    business_equity: float = 0.0
    public_equity: float = 0.0
    financial_assets: float = 0.0
    net_worth_p10: float = 0.0
    net_worth_p50: float = 0.0
    net_worth_p90: float = 0.0
    investable_assets: float = 0.0
    confidence: float = 0.0
    wealth_tier: str = "mass"
    coverage: dict[str, bool] = field(default_factory=dict)
    factors: list[Factor] = field(default_factory=list)


@dataclass
class PersonaScore:
    persona: str
    score: int
    factors: list[Factor]
    next_best_action: str


@dataclass
class ScoreResult:
    wealth: WealthEstimate
    personas: dict[str, PersonaScore]
    triggers: list[dict]

    def to_explanation(self) -> dict:
        return {
            "wealth": {
                **{k: v for k, v in asdict(self.wealth).items() if k != "factors"},
                "factors": [asdict(f) for f in self.wealth.factors],
            },
            "personas": {
                k: {"score": p.score, "next_best_action": p.next_best_action,
                    "factors": [asdict(f) for f in p.factors]}
                for k, p in self.personas.items()
            },
            "triggers": self.triggers,
        }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def wealth_tier(net_worth: float) -> str:
    if net_worth >= 30_000_000:
        return "ultra"
    if net_worth >= 5_000_000:
        return "vhnw"
    if net_worth >= 1_000_000:
        return "hnw"
    if net_worth >= 250_000:
        return "affluent"
    return "mass"


def remaining_mortgage(principal: float, years_elapsed: float, rate: float = 0.055, term_years: int = 30) -> float:
    """Remaining balance on a standard amortising mortgage."""
    if principal <= 0:
        return 0.0
    if years_elapsed >= term_years:
        return 0.0
    r = rate / 12
    n = term_years * 12
    k = max(0.0, years_elapsed) * 12
    paid_fraction = ((1 + r) ** k - 1) / ((1 + r) ** n - 1)
    return max(0.0, principal * (1 - paid_fraction))


def _years_since(d: datetime | None, now: datetime) -> float | None:
    if d is None:
        return None
    return max(0.0, (now - d).days / 365.25)


def _within(d: datetime | None, now: datetime, days: int) -> bool:
    return d is not None and 0 <= (now - d).days <= days


def _upcoming(d: datetime | None, now: datetime, days: int) -> bool:
    return d is not None and 0 <= (d - now).days <= days


# --------------------------------------------------------------------------- #
# Wealth estimation
# --------------------------------------------------------------------------- #
def estimate_wealth(signals: list[Sig], now: datetime | None = None) -> WealthEstimate:
    now = now or datetime.utcnow()
    est = WealthEstimate()
    by_kind: dict[str, list[Sig]] = {}
    for s in signals:
        by_kind.setdefault(s.kind, []).append(s)

    # -- coverage -----------------------------------------------------------
    present = {c: False for c in CATEGORIES}
    for s in signals:
        cat = SIGNAL_KINDS.get(s.kind, ("other", "", []))[0]
        if cat in present:
            present[cat] = True
    est.coverage = present

    # -- demographics -------------------------------------------------------
    demo = (by_kind.get("demographic.household") or [None])[0]
    age_band = demo.data.get("age_band") if demo else None
    zip_income = _num(demo.data.get("zip_median_income")) if demo else 0.0

    # -- income -------------------------------------------------------------
    income = 0.0
    emp = (by_kind.get("employment.title") or [None])[0]
    if emp:
        comp = _num(emp.data.get("est_comp"))
        if comp <= 0:
            comp = SENIORITY_COMP.get(emp.data.get("seniority", "ic"), 95_000)
            comp *= INDUSTRY_COMP_FACTOR.get(emp.data.get("industry", ""), 1.0)
        income = comp
        est.factors.append(Factor(
            "income_title", "Income from title / employer", comp,
            f"{emp.data.get('title', 'Unknown title')} at {emp.data.get('employer', 'unknown employer')}",
            [emp.id] if emp.id else [],
        ))
    if zip_income > 0:
        # Neighbourhood income is a weak prior; only lifts the estimate when we know nothing better.
        zip_based = zip_income * 1.6
        if income == 0:
            income = zip_based
            est.factors.append(Factor(
                "income_zip", "Income inferred from neighbourhood", zip_based,
                f"ZIP median household income ${zip_income:,.0f} × affluence prior", [demo.id] if demo.id else [],
            ))
    for b in by_kind.get("business.ownership", []):
        if b.data.get("status", "active") != "active":
            continue
        owner_draw = _num(b.data.get("est_revenue")) * 0.12 * (_num(b.data.get("ownership_pct"), 100) / 100)
        if owner_draw > 0:
            income += owner_draw
            est.factors.append(Factor(
                "income_business", "Owner income from business", owner_draw,
                f"~12% of ${_num(b.data.get('est_revenue')):,.0f} revenue at {b.data.get('entity')}",
                [b.id] if b.id else [],
            ))
    est.income_estimate = income

    # -- real estate --------------------------------------------------------
    for p in by_kind.get("property.owned", []):
        d = p.data
        value = _num(d.get("market_value")) or _num(d.get("assessed_value")) * 1.15
        if value <= 0:
            continue
        mortgage = d.get("mortgage_balance_est")
        if mortgage is None:
            purchase_price = _num(d.get("purchase_price"))
            yrs = _years_since(_dt(d.get("purchase_date")), now)
            if purchase_price > 0 and yrs is not None:
                mortgage = remaining_mortgage(purchase_price * 0.8, yrs)
            else:
                mortgage = value * 0.35
        equity = max(0.0, value - _num(mortgage))
        est.real_estate_equity += equity
        est.factors.append(Factor(
            "real_estate", "Real estate equity", equity,
            f"{d.get('address', 'Property')}: ${value:,.0f} value − ${_num(mortgage):,.0f} est. mortgage",
            [p.id] if p.id else [],
        ))

    # -- private business ---------------------------------------------------
    for b in by_kind.get("business.ownership", []):
        d = b.data
        if d.get("status", "active") != "active":
            continue
        rev = _num(d.get("est_revenue"))
        mult = INDUSTRY_REVENUE_MULTIPLE.get(d.get("industry", ""), 1.0)
        pct = _num(d.get("ownership_pct"), 100) / 100
        val = rev * mult * pct
        if val > 0:
            est.business_equity += val
            est.factors.append(Factor(
                "business", "Private business equity", val,
                f"{d.get('entity')}: ${rev:,.0f} revenue × {mult}x × {pct:.0%} owned",
                [b.id] if b.id else [],
            ))

    # -- public equity ------------------------------------------------------
    for h in by_kind.get("equity.insider_holding", []):
        val = _num(h.data.get("value")) or _num(h.data.get("shares")) * _num(h.data.get("price"))
        if val > 0:
            est.public_equity += val
            est.factors.append(Factor(
                "public_equity", "Public company holdings", val,
                f"{h.data.get('company')} ({h.data.get('ticker')}) — {h.data.get('role', 'insider')}",
                [h.id] if h.id else [],
            ))
    for l in by_kind.get("equity.ipo_lockup", []):
        val = _num(l.data.get("est_holding_value"))
        if val > 0:
            est.public_equity += val
            est.factors.append(Factor(
                "ipo_holding", "Post-IPO restricted holding", val,
                f"{l.data.get('company')} lockup expires {str(l.data.get('lockup_expiry', ''))[:10]}",
                [l.id] if l.id else [],
            ))

    # -- liquid financial assets -------------------------------------------
    base_mult = AGE_SAVINGS_MULTIPLIER.get(age_band or "", 2.0)
    # Higher earners save a larger share of income; scale the multiplier progressively.
    progressive = min(2.0, max(0.6, (income / 120_000) ** 0.35)) if income > 0 else 1.0
    mult = round(base_mult * progressive, 2)
    savings_model = income * mult
    if savings_model > 0:
        est.factors.append(Factor(
            "savings_model", "Accumulated savings (income × age multiplier)", savings_model,
            f"${income:,.0f} × {mult} (age {age_band or 'unknown'})", [demo.id] if demo and demo.id else [],
        ))
    liquidity = 0.0
    for t in by_kind.get("equity.insider_transaction", []):
        if t.data.get("type") == "sale" and _within(_dt(t.data.get("date")), now, 36 * 30):
            after_tax = _num(t.data.get("value")) * 0.65
            liquidity += after_tax
            est.factors.append(Factor(
                "liquidity_insider_sale", "Proceeds from stock sale", after_tax,
                f"Sold ${_num(t.data.get('value')):,.0f} of {t.data.get('ticker')} (after-tax est.)",
                [t.id] if t.id else [],
            ))
    for x in by_kind.get("business.exit", []):
        if _within(_dt(x.data.get("date")), now, 60 * 30):
            proceeds = _num(x.data.get("est_proceeds")) * 0.7
            liquidity += proceeds
            est.factors.append(Factor(
                "liquidity_exit", "Proceeds from business exit", proceeds,
                f"{x.data.get('event', 'exit')} of {x.data.get('entity')} (after-tax est.)",
                [x.id] if x.id else [],
            ))
    for s in by_kind.get("property.sold", []):
        gain = _num(s.data.get("sale_price")) - _num(s.data.get("purchase_price"))
        if gain > 0 and _within(_dt(s.data.get("sold_at")), now, 24 * 30):
            liquidity += gain * 0.5
            est.factors.append(Factor(
                "liquidity_property_sale", "Gain from property sale", gain * 0.5,
                f"{s.data.get('address')} sold for ${_num(s.data.get('sale_price')):,.0f}",
                [s.id] if s.id else [],
            ))

    # Philanthropy cross-check: major donors typically give ~2–3% of net worth / year.
    annual_giving = sum(_num(g.data.get("amount")) for g in by_kind.get("donation.charitable", []))
    giving_implied = annual_giving * 40
    financial = savings_model + liquidity
    if giving_implied > financial and annual_giving >= 5_000:
        blended = 0.6 * financial + 0.4 * giving_implied
        est.factors.append(Factor(
            "giving_capacity", "Giving-capacity adjustment", blended - financial,
            f"${annual_giving:,.0f}/yr charitable giving implies ~${giving_implied:,.0f} capacity",
            [g.id for g in by_kind.get("donation.charitable", []) if g.id],
        ))
        financial = blended
    est.financial_assets = financial

    # -- roll-up ------------------------------------------------------------
    p50 = est.real_estate_equity + est.business_equity + est.public_equity + est.financial_assets
    n_cov = sum(1 for c in ("property", "income", "demographic", "business", "equity", "giving") if present[c])
    avg_conf = (sum(s.confidence for s in signals) / len(signals)) if signals else 0.0
    conf = round(min(1.0, (n_cov / 6) * 0.7 + avg_conf * 0.3), 3)
    est.confidence = conf
    est.net_worth_p50 = round(p50)
    est.net_worth_p10 = round(p50 * (0.45 + 0.35 * conf))
    est.net_worth_p90 = round(p50 * (2.2 - 1.0 * conf))
    est.investable_assets = round(est.financial_assets + est.public_equity * 0.8)
    est.wealth_tier = wealth_tier(p50)
    est.income_estimate = round(est.income_estimate)
    est.real_estate_equity = round(est.real_estate_equity)
    est.business_equity = round(est.business_equity)
    est.public_equity = round(est.public_equity)
    est.financial_assets = round(est.financial_assets)
    return est


# --------------------------------------------------------------------------- #
# Timing triggers
# --------------------------------------------------------------------------- #
def detect_triggers(signals: list[Sig], now: datetime | None = None) -> list[dict]:
    """Recent or upcoming events that make *now* the right time to reach out."""
    now = now or datetime.utcnow()
    out: list[dict] = []

    def add(key: str, label: str, s: Sig, when: datetime | None, urgency: str = "warm") -> None:
        out.append({
            "key": key, "label": label, "signal_id": s.id, "urgency": urgency,
            "date": (when or s.observed_at).isoformat()[:10],
        })

    for s in signals:
        d = s.data
        if s.kind == "property.listed" and _within(_dt(d.get("listed_at")) or s.observed_at, now, 180):
            add("listed_home", "Home listed for sale", s, _dt(d.get("listed_at")), "hot")
        elif s.kind == "property.sold" and _within(_dt(d.get("sold_at")) or s.observed_at, now, 180):
            add("sold_home", "Sold a property", s, _dt(d.get("sold_at")), "hot")
        elif s.kind == "property.owned" and _within(_dt(d.get("purchase_date")), now, 365):
            add("bought_home", "Recently purchased a home", s, _dt(d.get("purchase_date")), "warm")
        elif s.kind == "equity.insider_transaction" and d.get("type") == "sale" and _within(_dt(d.get("date")), now, 365):
            add("insider_sale", f"Sold ${_num(d.get('value')):,.0f} of {d.get('ticker')}", s, _dt(d.get("date")), "hot")
        elif s.kind == "equity.ipo_lockup" and _upcoming(_dt(d.get("lockup_expiry")), now, 180):
            add("lockup_expiry", f"{d.get('ticker')} lockup expires soon", s, _dt(d.get("lockup_expiry")), "hot")
        elif s.kind == "business.exit" and _within(_dt(d.get("date")), now, 365):
            add("business_exit", f"Exited {d.get('entity')}", s, _dt(d.get("date")), "hot")
        elif s.kind == "business.ownership" and _within(_dt(d.get("formed_at")), now, 365):
            add("new_business", f"Formed {d.get('entity')}", s, _dt(d.get("formed_at")), "warm")
        elif s.kind == "employment.change" and _within(_dt(d.get("date")), now, 180):
            label = "New job" + (" — relocated" if d.get("relocated") else "")
            add("job_change", label, s, _dt(d.get("date")), "hot" if d.get("relocated") else "warm")
        elif s.kind == "life_event" and _within(_dt(d.get("date")), now, 365):
            t = str(d.get("type", "event"))
            urgency = "hot" if t in {"inheritance", "probate", "divorce", "retirement"} else "warm"
            add(f"life_{t}", t.replace("_", " ").capitalize(), s, _dt(d.get("date")), urgency)
        elif s.kind == "donation.charitable" and _num(d.get("amount")) >= 25_000 and _within(s.observed_at, now, 365):
            add("major_gift", f"Major gift to {d.get('org')}", s, None, "warm")
    order = {"hot": 0, "warm": 1}
    out.sort(key=lambda t: (order.get(t["urgency"], 2), t["date"]), reverse=False)
    return out


# --------------------------------------------------------------------------- #
# Persona propensity
# --------------------------------------------------------------------------- #
def _clamp(v: float) -> int:
    return int(max(0, min(100, round(v))))


def _life_events(signals: list[Sig], now: datetime, days: int) -> list[tuple[str, Sig]]:
    res = []
    for s in signals:
        if s.kind == "life_event" and _within(_dt(s.data.get("date")) or s.observed_at, now, days):
            res.append((str(s.data.get("type", "")), s))
    return res


def score_realtor(signals: list[Sig], w: WealthEstimate, now: datetime) -> PersonaScore:
    W = PERSONAS["realtor"]["weights"]
    f: list[Factor] = []
    pts = 15.0
    f.append(Factor("base", "Base rate", 15, "Population baseline for a 12-month move", []))

    props = [s for s in signals if s.kind == "property.owned"]
    primary = next((p for p in props if p.data.get("is_primary")), props[0] if props else None)
    if primary:
        yrs = _years_since(_dt(primary.data.get("purchase_date")), now)
        if yrs is not None:
            if yrs < 1.5:
                pts += W["just_bought_penalty"]
                f.append(Factor("just_bought", "Purchased in last 18 months", W["just_bought_penalty"],
                                f"Bought {yrs:.1f} years ago — unlikely to move", [primary.id]))
            elif 6 <= yrs <= 12:
                pts += W["tenure_sweet_spot"]
                f.append(Factor("tenure", "Tenure in move-up window", W["tenure_sweet_spot"],
                                f"{yrs:.0f} years in current home (peak move window is 6–12)", [primary.id]))
            elif yrs > 12:
                pts += W["tenure_sweet_spot"] * 0.5
                f.append(Factor("tenure", "Long tenure", W["tenure_sweet_spot"] * 0.5,
                                f"{yrs:.0f} years in current home — downsizing candidate", [primary.id]))
            elif yrs >= 3:
                pts += 5
                f.append(Factor("tenure", "Settling in", 5, f"{yrs:.0f} years in current home", [primary.id]))
        value = _num(primary.data.get("market_value")) or _num(primary.data.get("assessed_value")) * 1.15
        if value > 0 and w.real_estate_equity / max(value, 1) >= 0.5:
            pts += W["high_equity"]
            f.append(Factor("equity", "High home equity", W["high_equity"],
                            f"≈{w.real_estate_equity / value:.0%} equity — can fund a move-up", [primary.id]))
    if len(props) >= 2:
        pts += W["multi_property_investor"]
        f.append(Factor("investor", "Owns multiple properties", W["multi_property_investor"],
                        f"{len(props)} properties on record", [p.id for p in props]))

    listed = [s for s in signals if s.kind == "property.listed" and _within(_dt(s.data.get("listed_at")) or s.observed_at, now, 180)]
    if listed:
        pts += W["listed_home"]
        f.append(Factor("listed", "Home currently listed", W["listed_home"],
                        f"Listed at ${_num(listed[0].data.get('list_price')):,.0f}", [listed[0].id]))
    sold = [s for s in signals if s.kind == "property.sold" and _within(_dt(s.data.get("sold_at")) or s.observed_at, now, 180)]
    bought = [p for p in props if _within(_dt(p.data.get("purchase_date")), now, 365)]
    if sold and not bought:
        pts += W["sold_recently_no_purchase"]
        f.append(Factor("sold", "Sold recently, no new purchase found", W["sold_recently_no_purchase"],
                        "Likely renting or in a temporary situation — active buyer", [sold[0].id]))

    for t, s in _life_events(signals, now, 365):
        bonus = {"marriage": 12, "birth": 10, "divorce": 18, "retirement": 14, "relocation": 20, "inheritance": 8}.get(t, 0)
        if bonus:
            pts += bonus
            f.append(Factor(f"life_{t}", f"Life event: {t}", bonus, "Household change that commonly precedes a move", [s.id]))
    for s in signals:
        if s.kind == "employment.change" and _within(_dt(s.data.get("date")), now, 180):
            bonus = W["job_change_relocation"] if s.data.get("relocated") else 6
            pts += bonus
            f.append(Factor("job_change", "Job change" + (" with relocation" if s.data.get("relocated") else ""), bonus,
                            f"Now {s.data.get('new_title')} at {s.data.get('new_employer')}", [s.id]))
    if w.net_worth_p50 >= 1_000_000:
        pts += W["capacity_move_up"]
        f.append(Factor("capacity", "Capacity for a move-up purchase", W["capacity_move_up"],
                        f"Est. net worth ${w.net_worth_p50:,.0f}", []))

    top = max((x for x in f if x.value > 0 and x.name != "base"), key=lambda x: x.value, default=None)
    nba = {
        "listed": "They are already in market. Offer a buyer-side consult and a valuation second opinion.",
        "sold": "Reach out with curated listings that match their previous home profile.",
        "job_change": "Relocation outreach: neighbourhood guide + commute-based search.",
        "tenure": "Send an equity-position summary and a 'what your home is worth now' report.",
        "equity": "Send an equity-position summary and move-up affordability scenarios.",
        "investor": "Pitch investment inventory and 1031-exchange opportunities.",
    }.get(top.name.split("_")[0] if top else "", "Add to a quarterly market-update nurture.")
    return PersonaScore("realtor", _clamp(pts), f, nba)


def score_wealth_manager(signals: list[Sig], w: WealthEstimate, now: datetime) -> PersonaScore:
    W = PERSONAS["wealth_manager"]["weights"]
    f: list[Factor] = []
    pts = 10.0
    f.append(Factor("base", "Base rate", 10, "Population baseline", []))

    ia = w.investable_assets
    if ia >= 10_000_000:
        b = W["investable_assets"]
    elif ia >= 5_000_000:
        b = 30
    elif ia >= 1_000_000:
        b = 22
    elif ia >= 500_000:
        b = 12
    elif ia >= 250_000:
        b = 5
    else:
        b = -10
    pts += b
    f.append(Factor("investable", "Investable assets", b, f"Est. ${ia:,.0f} liquid + marketable", []))

    liq_recent = False
    for s in signals:
        d = s.data
        if s.kind == "equity.insider_transaction" and d.get("type") == "sale":
            dt = _dt(d.get("date"))
            if _within(dt, now, 365) and _num(d.get("value")) >= 250_000:
                liq_recent = True
                pts += W["liquidity_event_12m"]
                f.append(Factor("liquidity", "Liquidity event in last 12 months", W["liquidity_event_12m"],
                                f"Sold ${_num(d.get('value')):,.0f} of {d.get('ticker')}", [s.id]))
            elif _within(dt, now, 730) and _num(d.get("value")) >= 250_000:
                pts += 12
                f.append(Factor("liquidity", "Liquidity event in last 24 months", 12,
                                f"Sold ${_num(d.get('value')):,.0f} of {d.get('ticker')}", [s.id]))
        elif s.kind == "business.exit" and _within(_dt(d.get("date")), now, 365):
            liq_recent = True
            pts += W["liquidity_event_12m"]
            f.append(Factor("liquidity", "Business exit in last 12 months", W["liquidity_event_12m"],
                            f"{d.get('event')} of {d.get('entity')} — est. ${_num(d.get('est_proceeds')):,.0f}", [s.id]))
        elif s.kind == "property.sold" and _within(_dt(d.get("sold_at")), now, 365) and _num(d.get("sale_price")) >= 750_000:
            pts += 10
            f.append(Factor("liquidity", "Large property sale", 10,
                            f"{d.get('address')} sold for ${_num(d.get('sale_price')):,.0f}", [s.id]))
        elif s.kind == "equity.ipo_lockup" and _upcoming(_dt(d.get("lockup_expiry")), now, 180):
            pts += W["lockup_expiry_upcoming"]
            f.append(Factor("lockup", "IPO lockup expiring", W["lockup_expiry_upcoming"],
                            f"{d.get('ticker')} — est. ${_num(d.get('est_holding_value')):,.0f} becomes liquid", [s.id]))
        elif s.kind == "advisor.relationship":
            pts += W["has_advisor_penalty"]
            f.append(Factor("has_advisor", "Already has an advisor", W["has_advisor_penalty"],
                            f"{d.get('firm')} ({d.get('type', 'advisor')})", [s.id]))
        elif s.kind == "board.membership":
            pts += W["philanthropic_capacity"]
            f.append(Factor("philanthropy", "Nonprofit board seat", W["philanthropic_capacity"],
                            f"{d.get('role', 'Board member')} at {d.get('org')}", [s.id]))
    for t, s in _life_events(signals, now, 540):
        if t in {"inheritance", "probate"}:
            pts += W["inheritance"]
            f.append(Factor("inheritance", "Inheritance / estate event", W["inheritance"],
                            s.data.get("detail") or "Assets transferring", [s.id]))
        elif t == "retirement":
            pts += W["retirement_transition"]
            f.append(Factor("retirement", "Retirement transition", W["retirement_transition"],
                            "Rollover and income-planning window", [s.id]))
    demo = next((s for s in signals if s.kind == "demographic.household"), None)
    if demo and demo.data.get("age_band") in {"55-64"} and ia >= 500_000 and not any(x.name == "retirement" for x in f):
        pts += 8
        f.append(Factor("pre_retirement", "Pre-retirement age band", 8, "55–64 with meaningful assets", [demo.id]))
    if any(s.kind == "business.ownership" and s.data.get("status", "active") == "active" for s in signals):
        pts += W["business_owner_complexity"]
        f.append(Factor("owner", "Business owner", W["business_owner_complexity"],
                        "Concentrated, illiquid wealth — needs planning", []))

    if any(x.name == "lockup" for x in f):
        nba = "Pre-lockup outreach: 10b5-1 plan, concentrated-stock diversification and tax modelling."
    elif liq_recent:
        nba = "Post-liquidity outreach within 30 days: cash-management proposal and tax-aware deployment plan."
    elif any(x.name == "inheritance" for x in f):
        nba = "Offer an estate-settlement checklist and inherited-asset review."
    elif ia >= 1_000_000 and not any(x.name == "has_advisor" for x in f):
        nba = "Introduce via a second-opinion portfolio review."
    else:
        nba = "Add to quarterly thought-leadership nurture."
    return PersonaScore("wealth_manager", _clamp(pts), f, nba)


def score_financial_planner(signals: list[Sig], w: WealthEstimate, now: datetime) -> PersonaScore:
    W = PERSONAS["financial_planner"]["weights"]
    f: list[Factor] = []
    pts = 12.0
    f.append(Factor("base", "Base rate", 12, "Population baseline", []))

    for t, s in _life_events(signals, now, 540):
        bonus = {"marriage": 12, "birth": 14, "divorce": 15, "retirement": 16, "inheritance": 14,
                 "relocation": 8, "probate": 10}.get(t, 0)
        if bonus:
            pts += bonus
            f.append(Factor(f"life_{t}", f"Life transition: {t}", bonus, s.data.get("detail") or "Planning trigger", [s.id]))
    for s in signals:
        if s.kind == "employment.change" and _within(_dt(s.data.get("date")), now, 540):
            pts += 12
            f.append(Factor("job_change", "Job change", 12,
                            f"Now {s.data.get('new_title')} at {s.data.get('new_employer')} — 401(k) rollover / equity comp", [s.id]))
        elif s.kind == "business.ownership" and _within(_dt(s.data.get("formed_at")), now, 540):
            pts += W["life_transition"]
            f.append(Factor("new_business", "Newly formed business", W["life_transition"],
                            f"{s.data.get('entity')} — entity, retirement plan and tax setup", [s.id]))
        elif s.kind == "advisor.relationship":
            pts += W["has_advisor_penalty"]
            f.append(Factor("has_advisor", "Already has an advisor", W["has_advisor_penalty"],
                            f"{s.data.get('firm')}", [s.id]))

    ia = w.investable_assets
    if 250_000 <= ia <= 5_000_000:
        b = W["wealth_sweet_spot"]
        why = "Core planning market"
    elif 100_000 <= ia < 250_000:
        b, why = 8, "Emerging affluent"
    elif ia > 5_000_000:
        b, why = 5, "Likely served by private wealth"
    else:
        b, why = -5, "Below planning-fee threshold"
    pts += b
    f.append(Factor("sweet_spot", "Investable assets fit", b, f"${ia:,.0f} — {why}", []))

    demo = next((s for s in signals if s.kind == "demographic.household"), None)
    if demo:
        ab = demo.data.get("age_band")
        if ab in {"35-44", "45-54"}:
            pts += 8
            f.append(Factor("age", "Accumulation-phase age band", 8, f"Age {ab}", [demo.id]))
        elif ab == "55-64":
            pts += W["age_planning_window"]
            f.append(Factor("age", "Pre-retirement planning window", W["age_planning_window"], f"Age {ab}", [demo.id]))
    if any(s.kind == "business.ownership" and s.data.get("status", "active") == "active" for s in signals):
        pts += W["self_employed"]
        f.append(Factor("self_employed", "Self-employed / owner", W["self_employed"],
                        "Complex tax, retirement plan and succession needs", []))
    if w.income_estimate >= 200_000:
        pts += W["high_income"]
        f.append(Factor("income", "High income", W["high_income"], f"Est. ${w.income_estimate:,.0f}/yr", []))

    top = max((x for x in f if x.value > 0 and x.name != "base"), key=lambda x: x.value, default=None)
    nba = {
        "life": "Offer a transition-specific planning session (checklist for the event they just had).",
        "job": "Offer a 401(k) rollover + equity-compensation review.",
        "new": "Offer a business-owner setup package: entity, SEP/Solo 401(k), cash-flow plan.",
        "self": "Offer a business-owner tax and retirement review.",
        "sweet": "Invite to a flat-fee financial plan.",
    }.get(top.name.split("_")[0] if top else "", "Add to educational nurture.")
    return PersonaScore("financial_planner", _clamp(pts), f, nba)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def score_prospect(raw_signals: list, now: datetime | None = None) -> ScoreResult:
    now = now or datetime.utcnow()
    signals = [Sig.from_any(s) for s in raw_signals]
    wealth = estimate_wealth(signals, now)
    personas = {
        "realtor": score_realtor(signals, wealth, now),
        "wealth_manager": score_wealth_manager(signals, wealth, now),
        "financial_planner": score_financial_planner(signals, wealth, now),
    }
    return ScoreResult(wealth=wealth, personas=personas, triggers=detect_triggers(signals, now))
