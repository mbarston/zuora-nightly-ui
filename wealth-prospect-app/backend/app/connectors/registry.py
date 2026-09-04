"""
Connector registry: every data source the app knows about, with provenance
metadata and (where a free public API exists) a live implementation.

Design principle: prefer *public-record and first-party* sources over
purchased consumer data. WealthEngine's model leans on licensed credit-
bureau-derived and marketing-list data, which is expensive, opaque, and
increasingly restricted (CCPA/CPRA, state privacy laws, FCRA gray areas).
Public records, SEC filings, FEC filings, nonprofit 990s and business
registries are free or cheap, legally clean for marketing use, and — more
importantly — *explainable* to the end user.
"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx

from app.config import settings
from app.connectors import synthetic
from app.connectors.base import Connector, ConnectorMeta, ProspectIdentity
from app.scoring.signals import SignalDraft

log = logging.getLogger("prospect-lens.connectors")


class _SyntheticOnly(Connector):
    def fetch_synthetic(self, p: ProspectIdentity) -> list[SignalDraft]:
        return synthetic.generate(p).get(self.meta.key, [])


class PropertyRecords(_SyntheticOnly):
    meta = ConnectorMeta(
        key="property_records", name="Property records", category="property",
        description="County assessor + recorder data: ownership, assessed/market value, purchase price & date, "
                    "mortgages, listings and sales.",
        legal_basis="Public record. Free from most county open-data portals; national coverage via ATTOM, "
                    "CoreLogic or Regrid (licensed).",
        cost="Free (county) / $0.05–0.30 per lookup (aggregators)", coverage="US, ~95% of parcels",
        refresh="Weekly", signal_kinds=["property.owned", "property.listed", "property.sold"],
        docs_url="https://api.developer.attomdata.com/",
    )


class SecEdgar(Connector):
    meta = ConnectorMeta(
        key="sec_edgar", name="SEC EDGAR (Forms 3/4/5, S-1)", category="equity",
        description="Public-company insiders: holdings, sales, option exercises and IPO lockups. The single "
                    "best free source for *upcoming* liquidity.",
        legal_basis="Public record (SEC). Free full-text search API; fair-use rate limit 10 req/s with a User-Agent.",
        cost="Free", coverage="All US-listed company officers, directors and 10% holders",
        refresh="Daily", signal_kinds=["equity.insider_holding", "equity.insider_transaction", "equity.ipo_lockup"],
        docs_url="https://www.sec.gov/edgar/sec-api-documentation",
    )
    supports_live = True

    def fetch_synthetic(self, p: ProspectIdentity) -> list[SignalDraft]:
        return synthetic.generate(p).get("sec_edgar", [])

    def fetch_live(self, p: ProspectIdentity) -> list[SignalDraft]:  # pragma: no cover - network
        """Full-text search for Form 4 filings naming the prospect as reporting owner."""
        url = "https://efts.sec.gov/LatestSearch/index"
        params = {"q": f'"{p.full_name}"', "forms": "4", "dateRange": "custom",
                  "startdt": (datetime.utcnow().replace(year=datetime.utcnow().year - 2)).strftime("%Y-%m-%d")}
        headers = {"User-Agent": settings.SEC_USER_AGENT, "Accept": "application/json"}
        out: list[SignalDraft] = []
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])
        except Exception as exc:  # noqa: BLE001
            log.warning("SEC EDGAR lookup failed for %s: %s", p.full_name, exc)
            return out
        for h in hits[:10]:
            src = h.get("_source", {})
            names = src.get("display_names", [])
            company = next((n for n in names if "(CIK" in n and p.last_name.lower() not in n.lower()), names[0] if names else "Unknown")
            filed = src.get("file_date")
            out.append(SignalDraft(
                kind="equity.insider_transaction", source="sec_edgar", confidence=0.9,
                observed_at=datetime.fromisoformat(filed) if filed else None,
                summary=f"Form 4 filed re: {company}",
                data={"company": company, "ticker": "", "type": "filing", "value": 0, "date": filed,
                      "note": "Live EDGAR hit — parse the XML for transaction value in a later iteration"},
                source_ref=f"https://www.sec.gov/Archives/edgar/data/{h.get('_id', '').replace(':', '/')}",
                dedupe_key=f"edgar:{h.get('_id')}",
            ))
        return out


class Fec(Connector):
    meta = ConnectorMeta(
        key="fec", name="FEC individual contributions", category="giving",
        description="Federal political contributions by name + ZIP. Max-out donors ($3,300+) are a strong "
                    "affluence signal, and the record includes employer and occupation.",
        legal_basis="Public record (52 U.S.C. §30111). Note: FEC data may NOT be used to solicit "
                    "contributions or for commercial purposes in some readings — use only as an affluence signal, "
                    "never for solicitation lists. Consult counsel.",
        cost="Free (api.open.fec.gov, 1,000 req/hr with a key)", coverage="All US federal donors > $200",
        refresh="Weekly", signal_kinds=["donation.political"],
        docs_url="https://api.open.fec.gov/developers/",
    )
    supports_live = True

    def fetch_synthetic(self, p: ProspectIdentity) -> list[SignalDraft]:
        return synthetic.generate(p).get("fec", [])

    def fetch_live(self, p: ProspectIdentity) -> list[SignalDraft]:  # pragma: no cover - network
        url = "https://api.open.fec.gov/v1/schedules/schedule_a/"
        params = {"api_key": settings.FEC_API_KEY, "contributor_name": p.full_name, "per_page": 20,
                  "sort": "-contribution_receipt_date"}
        if p.zip:
            params["contributor_zip"] = p.zip[:5]
        out: list[SignalDraft] = []
        try:
            resp = httpx.get(url, params=params, timeout=15)
            resp.raise_for_status()
            rows = resp.json().get("results", [])
        except Exception as exc:  # noqa: BLE001
            log.warning("FEC lookup failed for %s: %s", p.full_name, exc)
            return out
        for r in rows:
            amt = float(r.get("contribution_receipt_amount") or 0)
            date = (r.get("contribution_receipt_date") or "")[:10]
            cmte = (r.get("committee") or {}).get("name") or "Unknown committee"
            out.append(SignalDraft(
                kind="donation.political", source="fec", confidence=0.9,
                observed_at=datetime.fromisoformat(date) if date else None,
                summary=f"${amt:,.0f} to {cmte}",
                data={"amount": amt, "recipient": cmte, "date": date, "cycle": r.get("two_year_transaction_period"),
                      "employer": r.get("contributor_employer"), "occupation": r.get("contributor_occupation")},
                source_ref=r.get("pdf_url") or "https://www.fec.gov/data/receipts/individual-contributions/",
                dedupe_key=f"fec:{r.get('sub_id')}",
            ))
        return out


class BusinessRegistry(Connector):
    meta = ConnectorMeta(
        key="business_registry", name="Business registrations", category="business",
        description="Secretary-of-State filings and officer records: who owns/controls which entities, when "
                    "they were formed, and dissolutions/mergers.",
        legal_basis="Public record. Free via state SoS portals; aggregated via OpenCorporates (API token, "
                    "free tier for non-commercial; commercial licence required for production).",
        cost="Free–$$ (OpenCorporates commercial licence)", coverage="US + 140 jurisdictions",
        refresh="Weekly", signal_kinds=["business.ownership", "business.exit"],
        docs_url="https://api.opencorporates.com/documentation/API-Reference",
    )
    supports_live = True

    def fetch_synthetic(self, p: ProspectIdentity) -> list[SignalDraft]:
        return synthetic.generate(p).get("business_registry", [])

    def fetch_live(self, p: ProspectIdentity) -> list[SignalDraft]:  # pragma: no cover - network
        url = "https://api.opencorporates.com/v0.4/officers/search"
        params = {"q": p.full_name, "per_page": 20}
        if p.state:
            params["jurisdiction_code"] = f"us_{p.state.lower()}"
        out: list[SignalDraft] = []
        try:
            resp = httpx.get(url, params=params, timeout=15)
            resp.raise_for_status()
            rows = resp.json().get("results", {}).get("officers", [])
        except Exception as exc:  # noqa: BLE001
            log.warning("OpenCorporates lookup failed for %s: %s", p.full_name, exc)
            return out
        for row in rows:
            o = row.get("officer", {})
            co = o.get("company", {})
            out.append(SignalDraft(
                kind="business.ownership", source="business_registry", confidence=0.6,
                summary=f"{o.get('position', 'Officer')} of {co.get('name')}",
                data={"entity": co.get("name"), "role": o.get("position"), "industry": "professional_services",
                      "est_revenue": 0, "ownership_pct": 0, "formed_at": co.get("incorporation_date"),
                      "status": "active" if not o.get("inactive") else "inactive"},
                source_ref=o.get("opencorporates_url"), dedupe_key=f"oc:{o.get('id')}",
            ))
        return out


class Nonprofit990(_SyntheticOnly):
    meta = ConnectorMeta(
        key="nonprofit_990", name="Nonprofit 990s & board seats", category="giving",
        description="IRS Form 990 filings list officers, directors and (for foundations) major grants. "
                    "Board seats and named gifts are strong affluence and philanthropic-intent signals.",
        legal_basis="Public record (IRS). Bulk XML from IRS + ProPublica Nonprofit Explorer API. Requires "
                    "building a person index from 990 Part VII — planned.",
        cost="Free", coverage="1.8M US nonprofits", refresh="Annual filings",
        signal_kinds=["donation.charitable", "board.membership"],
        docs_url="https://projects.propublica.org/nonprofits/api",
    )


class Employment(_SyntheticOnly):
    meta = ConnectorMeta(
        key="employment", name="Employment & titles", category="income",
        description="Job title, employer, seniority and job changes. First-party (CRM / import) and, "
                    "under licence, professional-network data providers.",
        legal_basis="First-party data from the customer's CRM or imports; third-party providers (e.g. "
                    "People Data Labs, Clearbit) under their commercial terms. No scraping.",
        cost="Free (first-party) / $0.03–0.20 per enrichment", coverage="Varies",
        refresh="Monthly", signal_kinds=["employment.title", "employment.change"],
    )


class Demographics(_SyntheticOnly):
    meta = ConnectorMeta(
        key="demographics", name="Neighbourhood & household", category="demographic",
        description="Census ACS ZIP-level medians (income, home value) plus household attributes the "
                    "customer already holds. Used only as a weak prior when nothing better exists.",
        legal_basis="Census ACS is public. Household attributes are first-party. No credit-bureau data.",
        cost="Free", coverage="All US ZIPs", refresh="Annual",
        signal_kinds=["demographic.household", "advisor.relationship"],
        docs_url="https://www.census.gov/data/developers/data-sets/acs-5year.html",
    )


class LifeEvents(_SyntheticOnly):
    meta = ConnectorMeta(
        key="life_events", name="Life events (court & vital records)", category="life",
        description="Probate filings, divorce filings, marriage records and change-of-address — the timing "
                    "signals that turn a wealthy name into a prospect who needs help *this quarter*.",
        legal_basis="Public court records (county). Sensitive: many states restrict commercial use of "
                    "vital records — gate per jurisdiction and consult counsel before enabling.",
        cost="Free–$ (county portals, UniCourt)", coverage="Varies by county",
        refresh="Weekly", signal_kinds=["life_event"],
    )


CONNECTORS: dict[str, Connector] = {
    c.meta.key: c for c in [
        PropertyRecords(), SecEdgar(), Fec(), BusinessRegistry(), Nonprofit990(), Employment(), Demographics(), LifeEvents()
    ]
}


def run_all(p: ProspectIdentity, live: bool | None = None) -> dict[str, list[SignalDraft]]:
    """Run every connector and return signals grouped by connector key."""
    live = settings.LIVE_CONNECTORS if live is None else live
    results: dict[str, list[SignalDraft]] = {}
    for key, c in CONNECTORS.items():
        try:
            results[key] = c.fetch(p, live=live)
        except Exception as exc:  # noqa: BLE001
            log.exception("connector %s failed: %s", key, exc)
            results[key] = []
    return results
