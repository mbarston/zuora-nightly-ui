"""
Tenant config helpers — defaults, validation, serialization to the run prompt.

The "default template" captures every hardcoded value that SKILL.md used to
carry inline. When a tenant is created, we clone this template into a fresh
TenantConfig row so the owner sees a working shape they can edit, not an
empty form. The example rate plan IDs are from Matt's CSBX sandbox — they
won't work in anyone else's tenant, and the UI makes that fact loud.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models import TenantConfig


# ---------------------------------------------------------------------------
# Defaults (loaded from the SKILL.md reference values)
# ---------------------------------------------------------------------------


DEFAULT_PRODUCTS: list[dict] = [
    {
        "label": "CloudStream SaaS Basic",
        "tier": 1,
        "rate_plans": [
            {
                "name": "Month to Month",
                "period": "MTM",
                "product_rate_plan_id": "8a8aa2a57f3a74c1017f41f294a26b3e",
            },
            {
                "name": "Annual Plan",
                "period": "Annual",
                "product_rate_plan_id": "8a8aa2a57f3a74c1017f41f295796b51",
            },
            {
                "name": "API Plan",
                "period": "Annual",
                "product_rate_plan_id": "8a8aa2a57f3a74c1017f41f293196b20",
            },
        ],
    },
    {
        "label": "CloudStream SaaS Pro",
        "tier": 2,
        "rate_plans": [
            {
                "name": "Month to Month",
                "period": "MTM",
                "product_rate_plan_id": "8a8aa0fc7e998c88017e9c6021fa1ac4",
            },
            {
                "name": "Annual Plan",
                "period": "Annual",
                "product_rate_plan_id": "8a8aa0fc7e998c88017e9c6022151ac9",
            },
        ],
    },
    {
        "label": "CloudStream SaaS Enterprise",
        "tier": 3,
        "rate_plans": [
            {
                "name": "Monthly Plan",
                "period": "MTM",
                "product_rate_plan_id": "8a8aa36a7f1c1e7d017f2336dd8c58a8",
            },
            {
                "name": "Annual Plan",
                "period": "Annual",
                "product_rate_plan_id": "8a8aa0fc7e998c88017e9c6022ff1af1",
            },
        ],
    },
]


DEFAULT_ADDONS: list[dict] = [
    {
        "name": "CloudStream Analytics Annual",
        "product_rate_plan_id": "8a8aa0fc7e998c88017e9c6026061b6a",
    },
    {
        "name": "CloudStream AI Insights Annual",
        "product_rate_plan_id": "8a8aa2028f0f5d55018f2cb1865d2d0a",
    },
]


DEFAULT_MANDATORY_SUBS: list[dict] = [
    {
        "subscription_number": "A-S00000354",
        "use_case": "Minimum Commit",
        "notes": "Post usage to draw down against the committed amount.",
    },
    {
        "subscription_number": "A-S00000355",
        "use_case": "Prepaid Drawdown (PPDD)",
        "notes": "Post usage to draw down prepaid balance.",
    },
    {
        "subscription_number": "A-S00000353",
        "use_case": "Prepaid Drawdown (PPDD) — second use case",
        "notes": "Post usage to draw down prepaid balance.",
    },
]


DEFAULT_TIER_MIX: dict[str, int] = {"1": 50, "2": 35, "3": 15}

DEFAULT_AMENDMENT_MIX: dict[str, int] = {
    "upgrade": 45,
    "add_product": 30,
    "downgrade": 10,
    "remove_product": 15,
}


DEFAULT_ACCOUNT_TYPE = "company"  # "company" (B2B) | "person" (B2C)

DEFAULT_NAME_POOL: dict[str, list[str]] = {
    "prefixes": [
        "Apex", "NovaBridge", "Quantum", "Skyline", "DataVault", "CloudForge",
        "PulsePoint", "Zenith", "ClearPath", "BlueStar", "MetricWave",
        "Streamline", "TerraCore", "Ironclad", "BrightLoop", "VectorScale",
    ],
    "suffixes": [
        "Technologies", "Software", "Systems", "Dynamics", "Analytics",
        "Labs", "Platforms", "Networks", "Digital", "AI", "Solutions", "Corp",
    ],
}

# B2C sample pool — the two lists become first names + last names. Surfaced by
# the UI when a tenant is switched to "person" mode.
DEFAULT_PERSON_NAME_POOL: dict[str, list[str]] = {
    "prefixes": [
        "James", "Maria", "David", "Sofia", "Michael", "Aisha", "Daniel",
        "Emma", "Carlos", "Priya", "Liam", "Hannah", "Noah", "Olivia",
        "Ethan", "Grace",
    ],
    "suffixes": [
        "Smith", "Johnson", "Williams", "Garcia", "Brown", "Patel", "Nguyen",
        "Martinez", "Lee", "Davis", "Rodriguez", "Wilson", "Khan", "Taylor",
    ],
}

DEFAULT_CURRENCY_MIX: dict[str, int] = {"USD": 100}

DEFAULT_PAYMENTS: dict = {
    "enabled": True,
    "pay_percentage_min": 60,
    "pay_percentage_max": 80,
    "payment_lag_days_min": 1,
    "payment_lag_days_max": 5,
}

DEFAULT_WRITEOFFS: dict = {
    "enabled": True,
    "frequency": "every_other_run",
    "count_min": 1,
    "count_max": 2,
    "max_invoice_amount": 500.00,
}


def seed_default_config(tenant_id: int) -> TenantConfig:
    """Build a fresh TenantConfig row pre-populated with the defaults above."""
    now = datetime.now(timezone.utc)
    return TenantConfig(
        tenant_id=tenant_id,
        products=[*DEFAULT_PRODUCTS],
        addons=[*DEFAULT_ADDONS],
        mandatory_subs=[*DEFAULT_MANDATORY_SUBS],
        new_subs_min=8,
        new_subs_max=15,
        amendments_min=6,
        amendments_max=12,
        cancellations_min=2,
        cancellations_max=4,
        usage_posts_min=5,
        usage_posts_max=10,
        tier_mix=dict(DEFAULT_TIER_MIX),
        amendment_mix=dict(DEFAULT_AMENDMENT_MIX),
        growth_bias_bp=100,
        account_type=DEFAULT_ACCOUNT_TYPE,
        name_pool=dict(DEFAULT_NAME_POOL),
        currency_mix=dict(DEFAULT_CURRENCY_MIX),
        payments=dict(DEFAULT_PAYMENTS),
        writeoffs=dict(DEFAULT_WRITEOFFS),
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass
class ValidationIssue:
    field: str          # e.g. "products", "tier_mix"
    severity: str       # "error" | "warning"
    message: str


def validate(config: TenantConfig | None) -> list[ValidationIssue]:
    """
    Return a list of issues. Empty list = OK to run.

    Hard errors block the run via the pre-run gate in app.runner.
    Warnings let the run proceed but surface on the dashboard + detail page.
    """
    issues: list[ValidationIssue] = []

    if config is None:
        issues.append(
            ValidationIssue(
                field="config",
                severity="error",
                message="This tenant has no configuration yet. Open 'Configure' to set it up.",
            )
        )
        return issues

    # --- products ---
    if not config.products:
        issues.append(
            ValidationIssue(
                field="products",
                severity="error",
                message="No products defined. Add at least two tiers so upgrades/downgrades have somewhere to go.",
            )
        )
    else:
        seen_tiers: set[int] = set()
        for idx, p in enumerate(config.products):
            if not p.get("label"):
                issues.append(
                    ValidationIssue(
                        f"products[{idx}].label", "error", f"Product #{idx + 1} has no label."
                    )
                )
            tier = p.get("tier")
            if not isinstance(tier, int) or tier < 1:
                issues.append(
                    ValidationIssue(
                        f"products[{idx}].tier",
                        "error",
                        f"Product '{p.get('label', '#' + str(idx + 1))}' has an invalid tier (must be a positive integer).",
                    )
                )
            else:
                seen_tiers.add(tier)
            if not p.get("rate_plans"):
                issues.append(
                    ValidationIssue(
                        f"products[{idx}].rate_plans",
                        "error",
                        f"Product '{p.get('label', '#' + str(idx + 1))}' has no rate plans.",
                    )
                )
            else:
                for rp_idx, rp in enumerate(p.get("rate_plans", [])):
                    if not rp.get("name"):
                        issues.append(
                            ValidationIssue(
                                f"products[{idx}].rate_plans[{rp_idx}].name",
                                "error",
                                f"A rate plan on '{p.get('label')}' has no name.",
                            )
                        )
                    if not rp.get("product_rate_plan_id"):
                        issues.append(
                            ValidationIssue(
                                f"products[{idx}].rate_plans[{rp_idx}].product_rate_plan_id",
                                "error",
                                f"Rate plan '{rp.get('name', '#' + str(rp_idx + 1))}' on "
                                f"'{p.get('label')}' has no product rate plan ID.",
                            )
                        )
        if len(seen_tiers) < 2:
            issues.append(
                ValidationIssue(
                    "products",
                    "warning",
                    "Only one tier defined — upgrades and downgrades won't be possible.",
                )
            )

    # --- mandatory subs ---
    if not config.mandatory_subs:
        issues.append(
            ValidationIssue(
                "mandatory_subs",
                "warning",
                "No mandatory usage subscriptions configured. PPDD / min-commit stories won't receive activity.",
            )
        )
    else:
        for idx, sub in enumerate(config.mandatory_subs):
            if not sub.get("subscription_number"):
                issues.append(
                    ValidationIssue(
                        f"mandatory_subs[{idx}].subscription_number",
                        "error",
                        f"Mandatory subscription #{idx + 1} has no subscription number.",
                    )
                )

    # --- volume ranges ---
    for lo_field, hi_field, label in [
        ("new_subs_min", "new_subs_max", "New subscriptions"),
        ("amendments_min", "amendments_max", "Amendments"),
        ("cancellations_min", "cancellations_max", "Cancellations"),
        ("usage_posts_min", "usage_posts_max", "Usage posts"),
    ]:
        lo = getattr(config, lo_field)
        hi = getattr(config, hi_field)
        if lo is None or hi is None or lo < 0 or hi < 0:
            issues.append(
                ValidationIssue(
                    lo_field,
                    "error",
                    f"{label}: min/max must be non-negative integers.",
                )
            )
        elif lo > hi:
            issues.append(
                ValidationIssue(
                    lo_field,
                    "error",
                    f"{label}: min ({lo}) cannot exceed max ({hi}).",
                )
            )

    # --- tier mix sums to 100 and only references defined tiers ---
    tier_mix = config.tier_mix or {}
    if not tier_mix:
        issues.append(
            ValidationIssue("tier_mix", "error", "Tier mix is empty. Add percentages for each product tier.")
        )
    else:
        total = sum(int(v or 0) for v in tier_mix.values())
        if total != 100:
            issues.append(
                ValidationIssue(
                    "tier_mix",
                    "error",
                    f"Tier mix percentages must sum to 100, got {total}.",
                )
            )
        defined_tiers = {str(p.get("tier")) for p in (config.products or [])}
        for k in tier_mix.keys():
            if defined_tiers and str(k) not in defined_tiers:
                issues.append(
                    ValidationIssue(
                        "tier_mix",
                        "warning",
                        f"Tier mix references tier '{k}' but no product has that tier.",
                    )
                )

    # --- amendment mix sums to 100 ---
    amendment_mix = config.amendment_mix or {}
    valid_amendment_keys = {"upgrade", "add_product", "downgrade", "remove_product"}
    if not amendment_mix:
        issues.append(
            ValidationIssue("amendment_mix", "error", "Amendment mix is empty.")
        )
    else:
        total = sum(int(v or 0) for v in amendment_mix.values())
        if total != 100:
            issues.append(
                ValidationIssue(
                    "amendment_mix",
                    "error",
                    f"Amendment mix percentages must sum to 100, got {total}.",
                )
            )
        for k in amendment_mix.keys():
            if k not in valid_amendment_keys:
                issues.append(
                    ValidationIssue(
                        "amendment_mix",
                        "warning",
                        f"Unknown amendment type '{k}' (expected one of {sorted(valid_amendment_keys)}).",
                    )
                )

    # --- currency mix ---
    currency_mix = config.currency_mix or {}
    if currency_mix:
        total = sum(int(v or 0) for v in currency_mix.values())
        if total != 100:
            issues.append(
                ValidationIssue(
                    "currency_mix",
                    "error",
                    f"Currency mix percentages must sum to 100, got {total}.",
                )
            )
        for k in currency_mix.keys():
            if not isinstance(k, str) or len(k) != 3:
                issues.append(
                    ValidationIssue(
                        "currency_mix",
                        "warning",
                        f"Currency code '{k}' should be a 3-letter ISO code (e.g. USD, EUR, GBP).",
                    )
                )

    # --- name pool ---
    pool = config.name_pool or {}
    if not pool.get("prefixes") or not pool.get("suffixes"):
        issues.append(
            ValidationIssue(
                "name_pool",
                "warning",
                "Name pool is missing prefixes or suffixes — new account names will fall back to the skill's defaults.",
            )
        )

    # --- payments ---
    payments = config.payments or {}
    if payments.get("enabled"):
        pmin = payments.get("pay_percentage_min", 60)
        pmax = payments.get("pay_percentage_max", 80)
        if not isinstance(pmin, (int, float)) or not isinstance(pmax, (int, float)):
            issues.append(ValidationIssue("payments", "error", "Pay percentage min/max must be numbers."))
        elif pmin < 0 or pmax > 100 or pmin > pmax:
            issues.append(ValidationIssue("payments", "error", f"Pay percentage range {pmin}–{pmax} is invalid (must be 0–100, min ≤ max)."))

    # --- writeoffs ---
    writeoffs = config.writeoffs or {}
    if writeoffs.get("enabled"):
        wmin = writeoffs.get("count_min", 1)
        wmax = writeoffs.get("count_max", 2)
        if not isinstance(wmin, int) or not isinstance(wmax, int) or wmin < 0 or wmax < wmin:
            issues.append(ValidationIssue("writeoffs", "error", f"Write-off count range {wmin}–{wmax} is invalid."))
        max_amt = writeoffs.get("max_invoice_amount", 500)
        if not isinstance(max_amt, (int, float)) or max_amt <= 0:
            issues.append(ValidationIssue("writeoffs", "error", "Write-off max invoice amount must be positive."))

    # --- growth bias sanity ---
    if config.growth_bias_bp is None or config.growth_bias_bp <= 0:
        issues.append(
            ValidationIssue(
                "growth_bias_bp",
                "error",
                "Growth bias must be > 0. Use 100 for neutral, 150 for 1.5x growth, etc.",
            )
        )

    return issues


def has_errors(issues: list[ValidationIssue]) -> bool:
    return any(i.severity == "error" for i in issues)


# ---------------------------------------------------------------------------
# Serialization to the run prompt
# ---------------------------------------------------------------------------


def to_prompt_markdown(tenant_name: str, config: TenantConfig) -> str:
    """
    Render a TenantConfig as a markdown section to append to the run prompt.

    The skill instructions tell the agent to treat this section as the
    authoritative configuration and IGNORE the hardcoded examples in SKILL.md.
    """
    lines: list[str] = []
    lines.append(f"## Tenant configuration for {tenant_name}")
    lines.append("")
    lines.append(
        "**IMPORTANT:** Use the values in this section as the ground truth. "
        "Any example IDs, volume ranges, tier mixes, or subscription numbers "
        "shown inside SKILL.md are reference-only and may not apply to this "
        "tenant."
    )
    lines.append("")

    # Products
    lines.append("### Products")
    if not config.products:
        lines.append("*(none defined — STOP and abort the run; the UI should have blocked this)*")
    else:
        for p in sorted(config.products, key=lambda x: x.get("tier", 999)):
            lines.append(f"- **{p.get('label', '?')}** (tier {p.get('tier')})")
            for rp in p.get("rate_plans", []):
                lines.append(
                    f"  - {rp.get('name', '?')} "
                    f"[{rp.get('period', '?')}] — "
                    f"`{rp.get('product_rate_plan_id', '?')}`"
                )
    lines.append("")

    # Add-ons
    lines.append("### Add-ons")
    if not config.addons:
        lines.append("*(none defined — do not attempt add-product / remove-product amendments)*")
    else:
        for a in config.addons:
            lines.append(f"- **{a.get('name', '?')}** — `{a.get('product_rate_plan_id', '?')}`")
    lines.append("")

    # Mandatory usage subs
    lines.append("### Mandatory usage subscriptions")
    lines.append(
        "Post usage to EVERY subscription listed below on every run, in "
        "addition to the random usage posts. Resolve each sub's active "
        "drawdown charge at runtime and use its actual UOM (don't assume "
        "\"API Call\")."
    )
    lines.append("")
    if not config.mandatory_subs:
        lines.append("*(none configured — skip the mandatory PPDD/min-commit step entirely)*")
    else:
        for sub in config.mandatory_subs:
            use_case = sub.get("use_case", "")
            notes = sub.get("notes", "")
            suffix = f" — {use_case}" if use_case else ""
            lines.append(f"- `{sub.get('subscription_number', '?')}`{suffix}")
            if notes:
                lines.append(f"    - {notes}")
    lines.append("")

    # Volume targets
    lines.append("### Volume ranges (pick randomly within each range)")
    lines.append(f"- New subscriptions: {config.new_subs_min}–{config.new_subs_max}")
    lines.append(f"- Amendments: {config.amendments_min}–{config.amendments_max}")
    lines.append(f"- Cancellations: {config.cancellations_min}–{config.cancellations_max}")
    lines.append(f"- Random usage posts: {config.usage_posts_min}–{config.usage_posts_max}")
    lines.append("")

    # Tier mix
    lines.append("### Tier distribution for new subscriptions")
    if config.tier_mix:
        for tier_key in sorted(config.tier_mix.keys(), key=lambda k: int(k)):
            lines.append(f"- Tier {tier_key}: {config.tier_mix[tier_key]}%")
    else:
        lines.append("*(not configured)*")
    lines.append("")

    # Amendment mix
    lines.append("### Amendment mix")
    label_map = {
        "upgrade": "Upgrade (move up a tier)",
        "downgrade": "Downgrade (move down a tier)",
        "add_product": "Add-product (attach an add-on)",
        "remove_product": "Remove-product (detach an add-on)",
    }
    if config.amendment_mix:
        for k, v in config.amendment_mix.items():
            lines.append(f"- {label_map.get(k, k)}: {v}%")
    else:
        lines.append("*(not configured)*")
    lines.append("")

    # Growth bias
    lines.append("### Growth bias")
    lines.append(
        f"- **{config.growth_bias:.2f}x** — multiplier on growth-oriented "
        "actions (new subs + upgrades + add-product). Values > 1.0 mean "
        "bias toward growth; < 1.0 biases toward churn. The final data story "
        "should still show growth outpacing churn, but the ratio tightens or "
        "widens based on this number."
    )
    lines.append("")

    # Name pool — interpretation depends on B2B (company) vs B2C (person).
    is_person = (getattr(config, "account_type", None) or "company") == "person"
    prefixes = (config.name_pool or {}).get("prefixes", [])
    suffixes = (config.name_pool or {}).get("suffixes", [])
    if is_person:
        lines.append("### Customer name pool (B2C)")
        lines.append(
            "- Accounts represent **individual consumers**, not businesses. "
            "Name each account after a real person and treat them as a "
            "single end customer."
        )
        if prefixes or suffixes:
            if prefixes:
                lines.append(f"- **First names:** {', '.join(prefixes)}")
            if suffixes:
                lines.append(f"- **Last names:** {', '.join(suffixes)}")
            lines.append(
                "- Generate each new account name by combining a random first "
                "name with a random last name (e.g. 'John Smith'). Avoid exact "
                "duplicates within the same run."
            )
        else:
            lines.append("*(use realistic individual person names of your choice)*")
    else:
        lines.append("### Company name pool (B2B)")
        lines.append(
            "- Accounts represent **businesses**. Name each account after a "
            "company."
        )
        if prefixes or suffixes:
            if prefixes:
                lines.append(f"- **Prefixes:** {', '.join(prefixes)}")
            if suffixes:
                lines.append(f"- **Suffixes:** {', '.join(suffixes)}")
            lines.append(
                "- Generate each new account name by combining a random prefix "
                "with a random suffix (e.g. 'Apex Technologies'). Avoid exact "
                "duplicates within the same run."
            )
        else:
            lines.append("*(use realistic tech-industry names of your choice)*")
    lines.append("")

    # Currency mix
    currency_mix = config.currency_mix or {}
    lines.append("### Currency distribution for new accounts")
    if currency_mix:
        for ccy, pct in sorted(currency_mix.items()):
            lines.append(f"- {ccy}: {pct}%")
        lines.append(
            "- When creating a new account, randomly assign a currency based on "
            "these percentages. Use the selected currency in the `newAccountJson` "
            '`"currency"` field instead of always using USD.'
        )
    else:
        lines.append("- **USD only** (default — all new accounts use USD)")
    lines.append("")

    # Payments
    payments = config.payments or {}
    lines.append("### Payments")
    if payments.get("enabled"):
        lines.append(f"- **Enabled** — apply payments to open invoices each run")
        lines.append(f"- Pay percentage: {payments.get('pay_percentage_min', 60)}–{payments.get('pay_percentage_max', 80)}% of open invoices")
        lines.append(f"- Payment lag: {payments.get('payment_lag_days_min', 1)}–{payments.get('payment_lag_days_max', 5)} days after invoice date")
    else:
        lines.append("- **Disabled** — skip payment application")
    lines.append("")

    # Write-offs
    writeoffs = config.writeoffs or {}
    lines.append("### Write-offs")
    if writeoffs.get("enabled"):
        lines.append(f"- **Enabled** — write off small invoices periodically")
        lines.append(f"- Frequency: {writeoffs.get('frequency', 'every_other_run')}")
        lines.append(f"- Count per run: {writeoffs.get('count_min', 1)}–{writeoffs.get('count_max', 2)} invoices")
        lines.append(f"- Max invoice amount: ${writeoffs.get('max_invoice_amount', 500):.2f}")
    else:
        lines.append("- **Disabled** — skip write-offs")
    lines.append("")

    return "\n".join(lines)
