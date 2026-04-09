"""
Catalog importer — read the tenant's product catalog via direct Zuora REST
and turn it into the shape TenantConfig expects.

We don't go through the Zuora MCP server for this because spawning a stdio
subprocess just to run two REST calls is overkill (and in Phase 3 we're not
inside a Claude session anyway — this runs when the user clicks "Import
from Zuora" in the config editor). Plain httpx is simpler and faster.

Import strategy:
  1. OAuth: POST /oauth/token with client_credentials
  2. Products: GET /v1/catalog/products?pageSize=40 (follows nextPage until done)
  3. Each product already contains its ProductRatePlans and (nested) charges.
  4. Classify products into "tier products" vs "add-ons" by heuristic —
     tiers have multiple rate plans OR names containing Basic / Pro /
     Standard / Enterprise / etc., add-ons typically have a single rate
     plan with "Annual" or "Add" in the name. We surface the guess in the
     UI and let the user correct it before saving.
  5. Assign an ordered tier number (1, 2, 3, ...) based on the product's
     apparent rank in the tier pecking order (best-effort string match).

Returns a preview dict the /config/import route renders as an HTMX form
fragment. Saving is a separate step — import does NOT clobber the user's
existing config automatically.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx


logger = logging.getLogger("zuora-se-agent.catalog_import")


# Rough pecking order for SaaS-style tier names. First match wins.
TIER_KEYWORDS: list[tuple[str, int]] = [
    ("free", 0),
    ("starter", 1),
    ("basic", 1),
    ("standard", 2),
    ("pro", 2),
    ("professional", 2),
    ("plus", 2),
    ("business", 3),
    ("premium", 3),
    ("enterprise", 4),
    ("ultimate", 4),
]


class CatalogImportError(RuntimeError):
    pass


@dataclass
class ImportedRatePlan:
    name: str
    period: str               # "MTM" | "Annual" | "Other"
    product_rate_plan_id: str


@dataclass
class ImportedProduct:
    label: str
    tier: int
    rate_plans: list[ImportedRatePlan] = field(default_factory=list)


@dataclass
class ImportedAddon:
    name: str
    product_rate_plan_id: str


@dataclass
class ImportPreview:
    products: list[ImportedProduct]
    addons: list[ImportedAddon]
    total_products_seen: int
    total_rate_plans_seen: int
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "products": [
                {
                    "label": p.label,
                    "tier": p.tier,
                    "rate_plans": [asdict(rp) for rp in p.rate_plans],
                }
                for p in self.products
            ],
            "addons": [asdict(a) for a in self.addons],
            "total_products_seen": self.total_products_seen,
            "total_rate_plans_seen": self.total_rate_plans_seen,
            "warnings": self.warnings,
        }


async def fetch_token(
    base_url: str, client_id: str, client_secret: str
) -> str:
    url = base_url.rstrip("/") + "/oauth/token"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code != 200:
        raise CatalogImportError(
            f"OAuth token request failed (HTTP {resp.status_code}): {resp.text[:300]}"
        )
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise CatalogImportError("OAuth response contained no access_token")
    return token


async def fetch_products(base_url: str, token: str) -> list[dict]:
    """Walk /v1/catalog/products with nextPage pagination until exhausted."""
    products: list[dict] = []
    next_url: str | None = (
        base_url.rstrip("/") + "/v1/catalog/products?pageSize=40"
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        while next_url:
            resp = await client.get(
                next_url, headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code != 200:
                raise CatalogImportError(
                    f"Products fetch failed (HTTP {resp.status_code}): {resp.text[:300]}"
                )
            payload = resp.json()
            products.extend(payload.get("products", []))
            # nextPage comes back as a full URL or a relative path; normalise.
            np = payload.get("nextPage")
            if np:
                next_url = np if np.startswith("http") else base_url.rstrip("/") + np
            else:
                next_url = None
    return products


def _infer_tier(name: str) -> int | None:
    lowered = name.lower()
    for keyword, tier in TIER_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lowered):
            return tier
    return None


def _infer_period(rate_plan_name: str) -> str:
    lowered = rate_plan_name.lower()
    if "month to month" in lowered or "monthly" in lowered or "mtm" in lowered or "m2m" in lowered:
        return "MTM"
    if "annual" in lowered or "yearly" in lowered or "year" in lowered:
        return "Annual"
    return "Other"


def classify(products_raw: list[dict]) -> ImportPreview:
    """
    Turn raw /v1/catalog/products payloads into ImportPreview.

    Heuristic:
      - A product with >1 rate plan and a recognisable tier keyword → tier product
      - A product with 1 rate plan OR name containing "add-on"/"analytics"/
        "insights"/etc. → add-on (we surface each rate plan as an add-on entry)
      - Everything else defaults to add-on; the user can re-classify in the form.
    """
    products: list[ImportedProduct] = []
    addons: list[ImportedAddon] = []
    warnings: list[str] = []
    rp_count = 0

    for prod in products_raw:
        name = prod.get("name") or ""
        rate_plans_raw = prod.get("productRatePlans") or []
        rp_count += len(rate_plans_raw)

        if not name or not rate_plans_raw:
            continue

        is_addon_signal = any(
            kw in name.lower()
            for kw in ("add-on", "addon", "analytics", "insights", "add on")
        )
        tier_guess = _infer_tier(name)

        if tier_guess is not None and len(rate_plans_raw) >= 1 and not is_addon_signal:
            # Classify as a tier product
            products.append(
                ImportedProduct(
                    label=name,
                    tier=tier_guess,
                    rate_plans=[
                        ImportedRatePlan(
                            name=rp.get("name") or "(unnamed)",
                            period=_infer_period(rp.get("name") or ""),
                            product_rate_plan_id=rp.get("id") or "",
                        )
                        for rp in rate_plans_raw
                        if rp.get("id")
                    ],
                )
            )
        else:
            # Treat every rate plan as a separate add-on entry
            for rp in rate_plans_raw:
                if not rp.get("id"):
                    continue
                rp_name = rp.get("name") or ""
                label = f"{name} — {rp_name}" if rp_name else name
                addons.append(
                    ImportedAddon(name=label, product_rate_plan_id=rp["id"])
                )

    # --- normalise tier numbers to 1..N with no gaps ---
    # Sort products by inferred tier number ascending, then relabel.
    products.sort(key=lambda p: p.tier)
    for i, p in enumerate(products, start=1):
        p.tier = i

    if not products:
        warnings.append(
            "No products matched any tier keyword (Basic/Pro/Enterprise/…). "
            "Everything was classified as an add-on — you'll need to manually "
            "promote one or more to tier products."
        )
    elif len(products) < 2:
        warnings.append(
            "Only one tier product found. Upgrades and downgrades won't work "
            "with a single tier."
        )

    return ImportPreview(
        products=products,
        addons=addons,
        total_products_seen=len(products_raw),
        total_rate_plans_seen=rp_count,
        warnings=warnings,
    )


async def import_catalog(
    base_url: str, client_id: str, client_secret: str
) -> ImportPreview:
    """One-shot: OAuth + products fetch + classify."""
    token = await fetch_token(base_url, client_id, client_secret)
    products_raw = await fetch_products(base_url, token)
    return classify(products_raw)
