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

import json
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


# Known Zuora data-center REST hosts, surfaced in the auth-failure hint so the
# user can spot a base-URL / data-center mismatch (the #1 cause of a generic
# 400 on /oauth/token — valid prod credentials only authenticate at their own
# data-center host, not the generic rest.zuora.com).
KNOWN_DATA_CENTER_HOSTS = (
    "rest.na.zuora.com",
    "rest.eu.zuora.com",
    "rest.apisandbox.zuora.com",
)


def _looks_like_dc_mismatch(status_code: int, body: str) -> bool:
    """
    Heuristic: distinguish a data-center/host mismatch from genuinely bad
    credentials on a 400/401 from /oauth/token.

    Zuora's OAuth endpoint returns the standard OAuth error shape
    (``{"error": "invalid_client", "error_description": "..."}``) when the
    client id/secret are wrong but the host is right. When the host is wrong
    (e.g. NA-provisioned client hitting the generic rest.zuora.com), the
    request never reaches the OAuth handler and we get a generic Spring error
    body instead (``{"timestamp", "status", "error", "path"}``) — no
    ``error_description`` / OAuth ``error`` key. We treat that as a likely
    host mismatch.
    """
    if status_code not in (400, 401):
        return False
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        # Non-JSON body (e.g. an HTML 404/proxy page) — also points at the
        # wrong host rather than bad credentials.
        return True
    if not isinstance(data, dict):
        return True
    oauth_error = str(data.get("error") or "")
    # The OAuth error shape carries error_description, or an OAuth-specific
    # error code like invalid_client / invalid_grant / unauthorized_client.
    if "error_description" in data:
        return False
    if oauth_error in {"invalid_client", "invalid_grant", "unauthorized_client", "invalid_request"}:
        return False
    # Generic Spring error shape (timestamp + path, no OAuth fields).
    if "timestamp" in data or "path" in data:
        return True
    return False


@dataclass
class ImportedRatePlan:
    name: str
    period: str               # "MTM" | "Annual" | "Other"
    product_rate_plan_id: str


@dataclass
class ImportedCatalogItem:
    """One Zuora product, with our best guess at how to use it.

    ``suggested_role`` is the default base/add-on split (driven by the Zuora
    ``category`` field, falling back to a name heuristic). The UI shows this
    as the default and lets the user flip any product before importing.
    The extra Zuora fields (sku/product_number/description) are surfaced
    purely to help the user make that call — add more here as needed.
    """
    label: str
    category: str | None       # raw Zuora category, e.g. "Base Products"
    suggested_role: str        # "base" | "addon"
    tier: int                  # suggested tier for base items; 0 for add-ons
    sku: str | None
    product_number: str | None
    description: str | None
    rate_plans: list[ImportedRatePlan] = field(default_factory=list)


# Zuora's standard Product.category enum values that map cleanly to a role.
_CATEGORY_BASE = "Base Products"
_CATEGORY_ADDON = "Add On Services"


@dataclass
class ImportPreview:
    items: list[ImportedCatalogItem]
    total_products_seen: int
    total_rate_plans_seen: int
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "items": [
                {
                    "label": it.label,
                    "category": it.category,
                    "suggested_role": it.suggested_role,
                    "tier": it.tier,
                    "sku": it.sku,
                    "product_number": it.product_number,
                    "description": it.description,
                    "rate_plans": [asdict(rp) for rp in it.rate_plans],
                }
                for it in self.items
            ],
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
        body = resp.text or ""
        if _looks_like_dc_mismatch(resp.status_code, body):
            host = base_url.rstrip("/").split("//", 1)[-1]
            raise CatalogImportError(
                f"Authentication failed (HTTP {resp.status_code}) against {host}. "
                "Verify the base URL matches your tenant's Zuora data center — "
                "credentials provisioned in one data center are rejected by every "
                "other host, including the generic rest.zuora.com. Common hosts: "
                + ", ".join(KNOWN_DATA_CENTER_HOSTS)
                + " (see Zuora's API docs for the full list)."
            )
        raise CatalogImportError(
            f"OAuth token request failed (HTTP {resp.status_code}): {body[:300]}"
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


def _suggest_role(name: str, category: str | None) -> str:
    """Decide base vs add-on. Zuora's ``category`` wins; otherwise guess by name.

    Zuora's standard Product.category enum maps directly:
      - "Base Products"   → base (tier products customers subscribe to)
      - "Add On Services" → add-on
    For products with no usable category (None / "Miscellaneous Products" /
    a custom value) we fall back to the old name heuristic and let the user
    flip the toggle in the import modal.
    """
    if category == _CATEGORY_BASE:
        return "base"
    if category == _CATEGORY_ADDON:
        return "addon"
    is_addon_signal = any(
        kw in name.lower()
        for kw in ("add-on", "addon", "analytics", "insights", "add on")
    )
    if is_addon_signal:
        return "addon"
    if _infer_tier(name) is not None:
        return "base"
    # Default unknowns to add-on; promoting in the UI is one click.
    return "addon"


def classify(products_raw: list[dict]) -> ImportPreview:
    """
    Turn raw /v1/catalog/products payloads into an ImportPreview of unified
    catalog items.

    Each Zuora product becomes one ImportedCatalogItem carrying a
    ``suggested_role`` (base/add-on) derived primarily from the Zuora
    ``category`` field. The UI renders the suggestion as the default and lets
    the user override per product before importing, so classification is no
    longer a one-shot guess.
    """
    items: list[ImportedCatalogItem] = []
    warnings: list[str] = []
    rp_count = 0
    uncategorised = 0

    for prod in products_raw:
        name = prod.get("name") or ""
        rate_plans_raw = prod.get("productRatePlans") or []
        rp_count += len(rate_plans_raw)

        if not name or not rate_plans_raw:
            continue

        category = prod.get("category")
        if category not in (_CATEGORY_BASE, _CATEGORY_ADDON):
            uncategorised += 1

        items.append(
            ImportedCatalogItem(
                label=name,
                category=category,
                suggested_role=_suggest_role(name, category),
                tier=_infer_tier(name) or 0,  # provisional; renumbered below
                sku=prod.get("sku"),
                product_number=prod.get("productNumber"),
                description=prod.get("description"),
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

    # --- assign sequential tier numbers (1..N) to base items only ---
    # Name-inferred tiers sort first (so Basic < Pro < Enterprise survives),
    # then everything is renumbered with no gaps so the generator's tier_mix
    # lines up. Add-on items carry tier 0.
    base_items = [it for it in items if it.suggested_role == "base"]
    base_items.sort(key=lambda it: (it.tier == 0, it.tier))
    for i, it in enumerate(base_items, start=1):
        it.tier = i
    for it in items:
        if it.suggested_role != "base":
            it.tier = 0

    if not base_items:
        warnings.append(
            "No products were classified as base/tier products. Use the "
            "Base / Add-on toggle to promote at least one so new subscriptions "
            "have something to start on."
        )
    elif len(base_items) < 2:
        warnings.append(
            "Only one base product found. Upgrades and downgrades won't work "
            "with a single tier — promote another product if you expect tier moves."
        )
    if uncategorised:
        warnings.append(
            f"{uncategorised} product(s) had no usable Zuora category; their "
            "base/add-on guess came from the product name. Double-check the "
            "toggle for those."
        )

    return ImportPreview(
        items=items,
        total_products_seen=len(products_raw),
        total_rate_plans_seen=rp_count,
        warnings=warnings,
    )


def extract_currencies(products_raw: list[dict]) -> dict[str, list[str]]:
    """Extract all currencies from the catalog, grouped by product rate plan.

    Returns a dict of ``{currency_code: [rate_plan_label, ...]}`` so the
    frontend can show which plans support each currency. Currencies are
    discovered from the ``pricing`` array on each ProductRatePlanCharge.
    """
    currency_plans: dict[str, set[str]] = {}

    for prod in products_raw:
        prod_name = prod.get("name") or "(unnamed)"
        for rp in prod.get("productRatePlans") or []:
            rp_name = rp.get("name") or ""
            label = f"{prod_name} — {rp_name}" if rp_name else prod_name
            for charge in rp.get("productRatePlanCharges") or []:
                for tier in charge.get("pricing") or []:
                    cur = tier.get("currency")
                    if cur:
                        currency_plans.setdefault(cur, set()).add(label)

    return {k: sorted(v) for k, v in sorted(currency_plans.items())}


async def import_currencies(
    base_url: str, client_id: str, client_secret: str
) -> dict[str, list[str]]:
    """One-shot: OAuth + products fetch + extract currencies per rate plan."""
    token = await fetch_token(base_url, client_id, client_secret)
    products_raw = await fetch_products(base_url, token)
    return extract_currencies(products_raw)


async def import_catalog(
    base_url: str, client_id: str, client_secret: str
) -> ImportPreview:
    """One-shot: OAuth + products fetch + classify."""
    token = await fetch_token(base_url, client_id, client_secret)
    products_raw = await fetch_products(base_url, token)
    return classify(products_raw)
