"""
Deterministic synthetic signal generator.

Given a prospect identity, derives an *archetype* (tech exec, business owner,
retiree, …) from a stable hash of the name and produces a coherent bundle of
signals for that archetype. The same prospect always gets the same story, so
demos and tests are reproducible, and "Enrich" on a hand-entered prospect
returns something plausible even with no live data sources configured.

Nothing here is real data. Names, addresses and companies are invented.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta

from app.connectors.base import ProspectIdentity
from app.scoring.signals import SignalDraft

ARCHETYPES = [
    # key, weight
    ("tech_exec", 12),
    ("business_owner", 16),
    ("physician", 8),
    ("attorney_partner", 6),
    ("finance_pro", 8),
    ("retiree", 10),
    ("inheritor", 4),
    ("re_investor", 7),
    ("young_professional", 14),
    ("mass_market", 15),
]

STREETS = ["Maple Ave", "Oak Ridge Rd", "Lakeshore Dr", "Summit Ct", "Highland Blvd", "Willow Ln",
           "Vista Way", "Harbor View", "Cedar Crest", "Ridgeline Dr", "Bayberry Ln", "Foxhall Rd"]

CITIES = [
    ("Austin", "TX", "78746", 145_000, 1_050_000), ("Scottsdale", "AZ", "85255", 128_000, 890_000),
    ("Naples", "FL", "34102", 118_000, 1_400_000), ("Palo Alto", "CA", "94301", 210_000, 3_400_000),
    ("Greenwich", "CT", "06830", 190_000, 2_100_000), ("Bellevue", "WA", "98004", 175_000, 1_900_000),
    ("Denver", "CO", "80206", 112_000, 980_000), ("Nashville", "TN", "37215", 121_000, 1_100_000),
    ("Charlotte", "NC", "28207", 108_000, 950_000), ("Plano", "TX", "75093", 115_000, 620_000),
    ("Boca Raton", "FL", "33432", 105_000, 980_000), ("Newport Beach", "CA", "92660", 168_000, 2_600_000),
    ("Chicago", "IL", "60614", 132_000, 890_000), ("Atlanta", "GA", "30327", 140_000, 1_200_000),
    ("Boston", "MA", "02116", 155_000, 1_500_000), ("Minneapolis", "MN", "55424", 150_000, 780_000),
    ("Columbus", "OH", "43221", 95_000, 520_000), ("Raleigh", "NC", "27608", 110_000, 760_000),
]

TECH_COS = [("Nimbus Data", "NMBD"), ("Corvid Systems", "CRVD"), ("Helio Robotics", "HLIO"),
            ("Vantage Cloud", "VNTG"), ("Quillon AI", "QLLN"), ("Fjord Semiconductor", "FJRD")]
PRIVATE_COS = ["Precision Dental Group", "Ridgeway Logistics", "Northstar HVAC", "Bluewater Marine Services",
               "Summit Orthopedics", "Harbor Point Builders", "Cascade Wealth Partners", "Redline Auto Group",
               "Pinecrest Senior Living", "Meridian Software Consulting", "Lakeside Hospitality Group",
               "Ironwood Manufacturing"]
INDUSTRIES = ["technology", "healthcare", "professional_services", "construction", "real_estate",
              "manufacturing", "hospitality", "finance", "legal", "retail"]
NONPROFITS = ["Children's Hospital Foundation", "Regional Food Bank", "Symphony Orchestra", "University Alumni Fund",
              "Museum of Art", "Habitat Coalition", "Community Land Trust", "Public Library Foundation"]
FIRMS = ["Merrill", "Morgan Stanley", "Edward Jones", "Fidelity", "Schwab Private Client", "Independent RIA"]
CANDIDATES = ["Committee for a Stronger Economy", "Friends of Senator Hale", "Ramirez for Congress",
              "Progress PAC", "Liberty Leadership Fund"]


def _rng(p: ProspectIdentity, salt: str = "") -> random.Random:
    key = f"{p.first_name}|{p.last_name}|{p.zip or ''}|{salt}".lower()
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def archetype_for(p: ProspectIdentity) -> str:
    r = _rng(p, "archetype")
    total = sum(w for _, w in ARCHETYPES)
    n = r.uniform(0, total)
    for key, w in ARCHETYPES:
        n -= w
        if n <= 0:
            return key
    return "mass_market"


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _city_for(p: ProspectIdentity, r: random.Random) -> tuple[str, str, str, int, int]:
    if p.city and p.state:
        match = next((c for c in CITIES if c[0] == p.city), None)
        if match:
            return match
        return (p.city, p.state, p.zip or "00000", 95_000, 550_000)
    return r.choice(CITIES)


def generate(p: ProspectIdentity, now: datetime | None = None) -> dict[str, list[SignalDraft]]:
    """Return signals grouped by connector key."""
    now = now or datetime.utcnow()
    r = _rng(p, "signals")
    arch = archetype_for(p)
    city, state, zipc, zip_income, zip_home = _city_for(p, r)
    out: dict[str, list[SignalDraft]] = {
        "property_records": [], "sec_edgar": [], "business_registry": [], "fec": [],
        "nonprofit_990": [], "employment": [], "demographics": [], "life_events": [],
    }

    # ---- demographics ----------------------------------------------------
    age_band = p.age_band or {
        "tech_exec": r.choice(["35-44", "45-54"]),
        "business_owner": r.choice(["45-54", "55-64"]),
        "physician": r.choice(["35-44", "45-54", "55-64"]),
        "attorney_partner": r.choice(["45-54", "55-64"]),
        "finance_pro": r.choice(["35-44", "45-54"]),
        "retiree": r.choice(["65-74", "75+"]),
        "inheritor": r.choice(["35-44", "45-54"]),
        "re_investor": r.choice(["45-54", "55-64"]),
        "young_professional": r.choice(["25-34", "35-44"]),
        "mass_market": r.choice(["25-34", "35-44", "45-54", "55-64"]),
    }[arch]
    marital = r.choices(["married", "single", "divorced", "widowed"], [60, 22, 12, 6])[0]
    out["demographics"].append(SignalDraft(
        kind="demographic.household", source="demographics", confidence=0.6,
        summary=f"Age {age_band}, {marital}, ZIP median income ${zip_income:,.0f}",
        data={"age_band": age_band, "marital_status": marital, "children": r.choice([0, 0, 1, 2, 2, 3]),
              "zip_median_income": zip_income, "zip_median_home_value": zip_home},
        dedupe_key="demographic",
    ))

    # ---- employment ------------------------------------------------------
    emp_map = {
        "tech_exec": (r.choice(["VP Engineering", "Chief Product Officer", "SVP Sales", "CTO"]), "vp", "technology"),
        "business_owner": ("Owner & CEO", "founder", None),
        "physician": (r.choice(["Orthopedic Surgeon", "Cardiologist", "Anesthesiologist", "Dermatologist"]), "physician", "healthcare"),
        "attorney_partner": ("Partner", "partner", "legal"),
        "finance_pro": (r.choice(["Managing Director", "Portfolio Manager", "Principal"]), "vp", "finance"),
        "retiree": ("Retired", "retired", "professional_services"),
        "inheritor": (r.choice(["Marketing Manager", "Consultant", "Nonprofit Director"]), "manager", "professional_services"),
        "re_investor": (r.choice(["Broker / Investor", "Principal"]), "director", "real_estate"),
        "young_professional": (r.choice(["Senior Software Engineer", "Product Manager", "Account Executive", "Nurse Practitioner"]), "senior_ic", r.choice(["technology", "healthcare"])),
        "mass_market": (r.choice(["Operations Manager", "Teacher", "Sales Representative", "Project Coordinator", "Electrician"]), r.choice(["ic", "manager"]), r.choice(["education", "retail", "manufacturing", "government"])),
    }
    title, seniority, industry = emp_map[arch]
    title = p.title or title
    employer = p.employer
    business = None
    if arch == "business_owner":
        business = r.choice(PRIVATE_COS)
        industry = industry or r.choice(INDUSTRIES)
        employer = employer or business
    elif arch == "tech_exec":
        employer = employer or r.choice(TECH_COS)[0]
    elif arch == "physician":
        employer = employer or r.choice(["Regional Medical Center", "University Hospital", "Summit Orthopedics"])
    elif arch == "attorney_partner":
        employer = employer or r.choice(["Whitfield & Crane LLP", "Baxter Rowe", "Hollis Marden LLP"])
    elif arch == "finance_pro":
        employer = employer or r.choice(["Ashford Capital", "Crestline Partners", "Sable Rock Advisors"])
    else:
        employer = employer or r.choice(["Metro School District", "Atlas Freight", "Beacon Health", "Coastal Utilities", "Northwind Retail"])
    out["employment"].append(SignalDraft(
        kind="employment.title", source="employment", confidence=0.75,
        summary=f"{title} at {employer}",
        data={"title": title, "employer": employer, "seniority": seniority, "industry": industry or "professional_services"},
        dedupe_key="employment.current",
    ))
    if r.random() < (0.22 if arch in {"tech_exec", "young_professional", "finance_pro"} else 0.08):
        d = now - timedelta(days=r.randint(10, 160))
        relocated = r.random() < 0.4
        out["employment"].append(SignalDraft(
            kind="employment.change", source="employment", confidence=0.7, observed_at=d,
            summary=f"Started as {title} at {employer}" + (" (relocated)" if relocated else ""),
            data={"new_title": title, "new_employer": employer, "old_employer": r.choice(["Prior Co", "Legacy Corp", "Former LLC"]),
                  "date": _iso(d), "relocated": relocated},
            dedupe_key=f"employment.change:{_iso(d)}",
        ))

    # ---- property --------------------------------------------------------
    home_mult = {"tech_exec": 1.6, "business_owner": 1.4, "physician": 1.5, "attorney_partner": 1.5, "finance_pro": 1.7,
                 "retiree": 1.0, "inheritor": 1.3, "re_investor": 1.2, "young_professional": 0.7, "mass_market": 0.55}[arch]
    n_props = {"re_investor": r.randint(2, 4), "business_owner": r.choice([1, 1, 2]), "retiree": r.choice([1, 1, 2]),
               "finance_pro": r.choice([1, 2]), "mass_market": r.choice([0, 1, 1, 1]), "young_professional": r.choice([0, 0, 1])}.get(arch, 1)
    tenure_years = {"retiree": r.uniform(12, 30), "young_professional": r.uniform(0.5, 5), "mass_market": r.uniform(1, 15)}.get(arch, r.uniform(1, 14))
    for i in range(n_props):
        is_primary = i == 0
        yrs = tenure_years if is_primary else r.uniform(1, 10)
        purchase_date = now - timedelta(days=int(yrs * 365.25))
        value = zip_home * home_mult * r.uniform(0.75, 1.35) * (1.0 if is_primary else r.uniform(0.4, 0.8))
        appreciation = (1.045 ** yrs)
        purchase_price = value / appreciation
        addr = f"{r.randint(100, 9800)} {r.choice(STREETS)}"
        out["property_records"].append(SignalDraft(
            kind="property.owned", source="property_records", confidence=0.85,
            summary=f"{'Primary residence' if is_primary else 'Additional property'}: {addr}, {city} {state} — est. ${value:,.0f}",
            data={"address": addr, "city": city, "state": state, "zip": zipc,
                  "property_type": r.choice(["single_family", "single_family", "condo", "townhome"]),
                  "market_value": round(value, -3), "assessed_value": round(value * 0.85, -3),
                  "purchase_price": round(purchase_price, -3), "purchase_date": _iso(purchase_date),
                  "sqft": r.randint(1400, 6500), "is_primary": is_primary},
            source_ref=f"county-assessor://{state}/{zipc}/{r.randint(100000, 999999)}",
            dedupe_key=f"property:{addr}",
        ))
        if is_primary and r.random() < 0.07:
            listed = now - timedelta(days=r.randint(3, 90))
            out["property_records"].append(SignalDraft(
                kind="property.listed", source="property_records", confidence=0.9, observed_at=listed,
                summary=f"Listed {addr} at ${value * 1.05:,.0f}",
                data={"address": addr, "list_price": round(value * 1.05, -3), "listed_at": _iso(listed)},
                dedupe_key=f"listed:{addr}",
            ))
    if r.random() < 0.06:
        sold = now - timedelta(days=r.randint(10, 150))
        addr = f"{r.randint(100, 9800)} {r.choice(STREETS)}"
        sale = zip_home * home_mult * r.uniform(0.7, 1.2)
        out["property_records"].append(SignalDraft(
            kind="property.sold", source="property_records", confidence=0.9, observed_at=sold,
            summary=f"Sold {addr} for ${sale:,.0f}",
            data={"address": addr, "sale_price": round(sale, -3), "sold_at": _iso(sold),
                  "purchase_price": round(sale * r.uniform(0.5, 0.85), -3)},
            dedupe_key=f"sold:{addr}",
        ))

    # ---- business --------------------------------------------------------
    if arch == "business_owner":
        formed = now - timedelta(days=r.randint(200, 9000))
        rev = r.choice([1.2e6, 2.5e6, 4e6, 8e6, 15e6, 30e6]) * r.uniform(0.8, 1.2)
        out["business_registry"].append(SignalDraft(
            kind="business.ownership", source="business_registry", confidence=0.8,
            summary=f"Owner of {business} ({industry}), est. revenue ${rev:,.0f}",
            data={"entity": business, "role": "Owner / Managing Member", "industry": industry, "est_revenue": round(rev, -3),
                  "ownership_pct": r.choice([100, 100, 75, 50]), "formed_at": _iso(formed), "status": "active"},
            source_ref=f"sos://{state}/{r.randint(10**7, 10**8)}", dedupe_key=f"business:{business}",
        ))
        if r.random() < 0.12:
            d = now - timedelta(days=r.randint(20, 300))
            out["business_registry"].append(SignalDraft(
                kind="business.exit", source="business_registry", confidence=0.7, observed_at=d,
                summary=f"Sold {business}",
                data={"entity": business, "event": "acquisition", "est_proceeds": round(rev * 1.5, -4), "date": _iso(d)},
                dedupe_key=f"exit:{business}",
            ))
            out["business_registry"][0].data["status"] = "sold"
    elif arch in {"re_investor", "physician", "attorney_partner"} and r.random() < 0.5:
        ent = f"{p.last_name} {'Holdings' if arch == 're_investor' else 'Professional'} LLC"
        formed = now - timedelta(days=r.randint(60, 4000))
        rev = r.choice([300e3, 600e3, 1.2e6]) * r.uniform(0.8, 1.3)
        out["business_registry"].append(SignalDraft(
            kind="business.ownership", source="business_registry", confidence=0.75,
            summary=f"Managing member of {ent}",
            data={"entity": ent, "role": "Managing Member", "industry": "real_estate" if arch == "re_investor" else "professional_services",
                  "est_revenue": round(rev, -3), "ownership_pct": 100, "formed_at": _iso(formed), "status": "active"},
            source_ref=f"sos://{state}/{r.randint(10**7, 10**8)}", dedupe_key=f"business:{ent}",
        ))
    elif arch == "young_professional" and r.random() < 0.1:
        ent = f"{p.first_name} {p.last_name} Consulting LLC"
        formed = now - timedelta(days=r.randint(20, 300))
        out["business_registry"].append(SignalDraft(
            kind="business.ownership", source="business_registry", confidence=0.7,
            summary=f"Formed {ent}",
            data={"entity": ent, "role": "Member", "industry": "professional_services", "est_revenue": 150_000,
                  "ownership_pct": 100, "formed_at": _iso(formed), "status": "active"},
            dedupe_key=f"business:{ent}",
        ))

    # ---- public equity ---------------------------------------------------
    if arch == "tech_exec":
        co, ticker = r.choice(TECH_COS)
        value = r.choice([600e3, 1.5e6, 3e6, 8e6, 20e6]) * r.uniform(0.7, 1.3)
        out["sec_edgar"].append(SignalDraft(
            kind="equity.insider_holding", source="sec_edgar", confidence=0.9,
            summary=f"Section 16 insider at {co} ({ticker}) — est. ${value:,.0f}",
            data={"company": co, "ticker": ticker, "shares": int(value / 42), "price": 42.0, "value": round(value, -3), "role": title},
            source_ref=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={co.replace(' ', '+')}",
            dedupe_key=f"holding:{ticker}",
        ))
        if r.random() < 0.45:
            d = now - timedelta(days=r.randint(5, 400))
            sale = value * r.uniform(0.1, 0.4)
            out["sec_edgar"].append(SignalDraft(
                kind="equity.insider_transaction", source="sec_edgar", confidence=0.95, observed_at=d,
                summary=f"Form 4: sold ${sale:,.0f} of {ticker}",
                data={"company": co, "ticker": ticker, "type": "sale", "value": round(sale, -3), "date": _iso(d)},
                source_ref="https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4",
                dedupe_key=f"form4:{ticker}:{_iso(d)}",
            ))
        if r.random() < 0.2:
            expiry = now + timedelta(days=r.randint(20, 170))
            out["sec_edgar"].append(SignalDraft(
                kind="equity.ipo_lockup", source="sec_edgar", confidence=0.85,
                summary=f"{ticker} IPO lockup expires {_iso(expiry)}",
                data={"company": co, "ticker": ticker, "ipo_date": _iso(expiry - timedelta(days=180)),
                      "lockup_expiry": _iso(expiry), "est_holding_value": round(value, -3)},
                dedupe_key=f"lockup:{ticker}",
            ))

    # ---- giving ----------------------------------------------------------
    give_p = {"tech_exec": 0.5, "business_owner": 0.55, "physician": 0.45, "attorney_partner": 0.6, "finance_pro": 0.55,
              "retiree": 0.5, "inheritor": 0.7, "re_investor": 0.35, "young_professional": 0.12, "mass_market": 0.08}[arch]
    if r.random() < give_p:
        amt = r.choice([1_000, 2_900, 3_300, 5_000, 10_000, 25_000]) if arch != "mass_market" else r.choice([100, 250, 500])
        d = now - timedelta(days=r.randint(15, 700))
        cand = r.choice(CANDIDATES)
        out["fec"].append(SignalDraft(
            kind="donation.political", source="fec", confidence=0.95, observed_at=d,
            summary=f"${amt:,.0f} to {cand}",
            data={"amount": amt, "recipient": cand, "date": _iso(d), "cycle": 2026 if d.year >= 2025 else 2024},
            source_ref="https://www.fec.gov/data/receipts/individual-contributions/",
            dedupe_key=f"fec:{cand}:{_iso(d)}",
        ))
    if r.random() < give_p * 0.8:
        org = r.choice(NONPROFITS)
        amt = r.choice([2_500, 5_000, 10_000, 25_000, 50_000, 100_000]) if arch != "mass_market" else 500
        out["nonprofit_990"].append(SignalDraft(
            kind="donation.charitable", source="nonprofit_990", confidence=0.65,
            summary=f"${amt:,.0f} gift to {org} ({now.year - 1})",
            data={"amount": amt, "org": org, "year": now.year - 1},
            dedupe_key=f"gift:{org}",
        ))
        if amt >= 25_000 or r.random() < 0.3:
            out["nonprofit_990"].append(SignalDraft(
                kind="board.membership", source="nonprofit_990", confidence=0.8,
                summary=f"Board member, {org}",
                data={"org": org, "role": r.choice(["Trustee", "Board Member", "Treasurer"]), "org_revenue": r.choice([2e6, 8e6, 25e6])},
                source_ref="https://projects.propublica.org/nonprofits/",
                dedupe_key=f"board:{org}",
            ))

    # ---- life events -----------------------------------------------------
    if arch == "inheritor" or r.random() < 0.04:
        d = now - timedelta(days=r.randint(30, 400))
        out["life_events"].append(SignalDraft(
            kind="life_event", source="life_events", confidence=0.6, observed_at=d,
            summary="Probate filing — beneficiary of estate",
            data={"type": "inheritance", "date": _iso(d), "detail": f"Named beneficiary in {r.choice(['parent', 'relative'])}'s estate (probate record)"},
            source_ref="county-probate://record", dedupe_key="life:inheritance",
        ))
    if arch == "retiree" and r.random() < 0.35:
        d = now - timedelta(days=r.randint(30, 500))
        out["life_events"].append(SignalDraft(
            kind="life_event", source="life_events", confidence=0.6, observed_at=d,
            summary="Retired", data={"type": "retirement", "date": _iso(d), "detail": "Retirement announced"},
            dedupe_key="life:retirement",
        ))
    if arch in {"young_professional", "mass_market", "tech_exec", "physician"} and r.random() < 0.18:
        d = now - timedelta(days=r.randint(20, 360))
        t = r.choice(["marriage", "birth", "birth", "relocation"])
        out["life_events"].append(SignalDraft(
            kind="life_event", source="life_events", confidence=0.55, observed_at=d,
            summary=t.capitalize(), data={"type": t, "date": _iso(d), "detail": {"marriage": "Marriage record", "birth": "New child in household", "relocation": "Change of address"}[t]},
            dedupe_key=f"life:{t}",
        ))
    if arch in {"business_owner", "attorney_partner", "finance_pro"} and r.random() < 0.08:
        d = now - timedelta(days=r.randint(20, 400))
        out["life_events"].append(SignalDraft(
            kind="life_event", source="life_events", confidence=0.6, observed_at=d,
            summary="Divorce filing", data={"type": "divorce", "date": _iso(d), "detail": "Divorce filing (court record)"},
            dedupe_key="life:divorce",
        ))

    # ---- existing advisor ------------------------------------------------
    adv_p = {"tech_exec": 0.35, "business_owner": 0.3, "physician": 0.4, "attorney_partner": 0.45, "finance_pro": 0.5,
             "retiree": 0.55, "inheritor": 0.2, "re_investor": 0.3, "young_professional": 0.1, "mass_market": 0.08}[arch]
    if r.random() < adv_p:
        out["demographics"].append(SignalDraft(
            kind="advisor.relationship", source="demographics", confidence=0.5,
            summary=f"Existing relationship with {r.choice(FIRMS)}",
            data={"firm": r.choice(FIRMS), "type": "wealth_advisor", "since": now.year - r.randint(1, 10)},
            dedupe_key="advisor",
        ))
    return out
