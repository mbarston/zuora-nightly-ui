"""
Catalog of signal kinds. A signal is one observed fact from one source.

Every connector emits signals of these kinds with the documented `data`
shape, and the scoring engine only ever reads signals — never raw source
payloads. That keeps the model explainable and makes adding a new data
source a matter of mapping it onto this vocabulary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SignalDraft:
    kind: str
    source: str
    summary: str
    data: dict = field(default_factory=dict)
    confidence: float = 0.7
    observed_at: datetime | None = None
    source_ref: str | None = None
    dedupe_key: str | None = None


# kind -> (category, human label, expected data keys)
SIGNAL_KINDS: dict[str, tuple[str, str, list[str]]] = {
    "property.owned": (
        "property",
        "Owns property",
        ["address", "city", "state", "zip", "property_type", "market_value", "assessed_value",
         "purchase_price", "purchase_date", "mortgage_balance_est", "sqft", "is_primary"],
    ),
    "property.listed": ("property", "Home listed for sale", ["address", "list_price", "listed_at"]),
    "property.sold": ("property", "Property sold", ["address", "sale_price", "sold_at", "purchase_price"]),
    "equity.insider_holding": ("equity", "Public company insider holding",
                               ["company", "ticker", "shares", "price", "value", "role"]),
    "equity.insider_transaction": ("equity", "Insider transaction (Form 4)",
                                   ["company", "ticker", "type", "value", "date"]),
    "equity.ipo_lockup": ("equity", "IPO lockup expiry",
                          ["company", "ticker", "ipo_date", "lockup_expiry", "est_holding_value"]),
    "business.ownership": ("business", "Business ownership",
                           ["entity", "role", "industry", "est_revenue", "ownership_pct", "formed_at", "status"]),
    "business.exit": ("business", "Business exit / liquidity event",
                      ["entity", "event", "est_proceeds", "date"]),
    "donation.political": ("giving", "Political contribution (FEC)", ["amount", "recipient", "date", "cycle"]),
    "donation.charitable": ("giving", "Charitable gift", ["amount", "org", "year"]),
    "board.membership": ("giving", "Nonprofit board seat", ["org", "role", "org_revenue"]),
    "employment.title": ("income", "Job title / employer",
                         ["title", "employer", "seniority", "industry", "est_comp"]),
    "employment.change": ("income", "Job change", ["new_title", "new_employer", "old_employer", "date", "relocated"]),
    "demographic.household": ("demographic", "Household profile",
                              ["age_band", "marital_status", "children", "zip_median_income",
                               "zip_median_home_value"]),
    "life_event": ("life", "Life event", ["type", "date", "detail"]),
    "advisor.relationship": ("advisor", "Existing advisor relationship", ["firm", "type", "since"]),
}

CATEGORIES = ["property", "income", "demographic", "business", "equity", "giving", "life", "advisor"]

LIFE_EVENT_TYPES = ["marriage", "birth", "divorce", "retirement", "inheritance", "relocation", "probate"]

SENIORITY_COMP: dict[str, float] = {
    "ic": 95_000,
    "senior_ic": 150_000,
    "manager": 165_000,
    "director": 240_000,
    "vp": 380_000,
    "cxo": 650_000,
    "founder": 300_000,
    "partner": 550_000,
    "physician": 340_000,
    "attorney": 260_000,
    "retired": 90_000,
}

INDUSTRY_COMP_FACTOR: dict[str, float] = {
    "technology": 1.35,
    "finance": 1.45,
    "healthcare": 1.15,
    "legal": 1.2,
    "real_estate": 1.05,
    "professional_services": 1.0,
    "manufacturing": 0.9,
    "retail": 0.75,
    "education": 0.7,
    "nonprofit": 0.7,
    "government": 0.8,
    "energy": 1.1,
}

# Private business valuation as a multiple of revenue (rough, conservative).
INDUSTRY_REVENUE_MULTIPLE: dict[str, float] = {
    "technology": 2.5,
    "finance": 2.0,
    "healthcare": 1.4,
    "legal": 1.1,
    "real_estate": 2.0,
    "professional_services": 1.0,
    "manufacturing": 0.9,
    "retail": 0.5,
    "construction": 0.6,
    "hospitality": 0.7,
    "energy": 1.2,
}

# Wealth accumulation multiplier: liquid financial assets ≈ income × multiplier.
# Calibrated so a median earner lands near Fed SCF median liquid wealth for the
# band, while high earners (who save a larger share) scale up progressively —
# see `estimate_wealth` which multiplies by (income / 120k) ** 0.35.
AGE_SAVINGS_MULTIPLIER: dict[str, float] = {
    "18-24": 0.15,
    "25-34": 0.5,
    "35-44": 1.3,
    "45-54": 2.6,
    "55-64": 4.2,
    "65-74": 5.2,
    "75+": 4.6,
}
