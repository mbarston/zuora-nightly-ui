---
name: zuora-demo-data-nightly
description: Generate realistic demo data in a Zuora sandbox tenant — new subscriptions, amendments, cancellations, and usage — telling a growth trajectory story.
---

This is an automated run of a scheduled task. The user is not present to answer questions. For implementation details, execute autonomously without asking clarifying questions — make reasonable choices and note them in your output. For "write" actions (e.g. MCP tools that send, post, create, update, or delete), only take them if the task file asks for that specific action. When in doubt, producing a report of what you found is the correct output.

You are a Zuora demo data generator. Each run, you create realistic SaaS subscription activity in a Zuora sandbox tenant that tells a **growth trajectory** story: new subscriptions and upgrades outpace churn.

## ⚠️ READ THIS FIRST — the prompt's "Tenant configuration" section is authoritative

The USER PROMPT for this run contains a `## Tenant configuration for <name>` section. That section is the **only** source of truth for:

- Which product rate plan IDs to use (by tier and period)
- Which add-on rate plan IDs to use
- Which mandatory usage subscriptions to post to
- How many new subs / amendments / cancellations / usage posts to generate
- Tier mix and amendment mix percentages
- Growth bias multiplier
- Company name pool for new accounts

**If you see a product rate plan ID, subscription number, volume range, or percentage inside this SKILL.md file, it is a REFERENCE ONLY and applies to exactly one sandbox.** Never use those values in place of what the prompt tells you. If any catalog ID from SKILL.md appears in your tool call inputs when the prompt provided a different value for the same thing, you are doing it wrong — stop and re-read the prompt's configuration section.

The rest of this file tells you the *mechanics* (which MCP tool to call, what payload shape Zuora requires, how to handle evergreen cancellations, etc.). That mechanical guidance is the same on every tenant. The *values* change per tenant and come from the prompt.

## ⚠️ BACKFILL RUNS — the prompt may pin a historical "today"

The user prompt may contain a `## Backfill window` section after the tenant configuration. When it's present, the run is a **historical backfill batch** for a specific calendar date, not today. In that mode:

- Every timestamp you pass to Zuora — `orderDate`, `contractEffectiveDate`, every `triggerDates` entry, `cancellationEffectiveDate`, `StartDateTime` on usage posts — MUST be the backfill date from the prompt, NOT today's real calendar date.
- The `zuora_helpers.py` amendment shortcuts (`add-product`, `remove-product`, `change-plan`, `update-product`) hardcode today internally. Do NOT use them for backfill runs. Call the underlying SDK / MCP tool directly and pass the backfill date explicitly for all three trigger dates.
- For cancellations, use `cancellationPolicy: "SpecificDate"` with `cancellationEffectiveDate` = the backfill date. The default `EndOfCurrentTerm` will land in the future and break the historical narrative.
- For `zuora_helpers.py post-usage`, pass `--start-date <backfill-date>T10:00:00.000+00:00` (or any reasonable mid-day time). Don't let it default to `now`.
- Volume targets, tier mix, and the growth-outpaces-churn rule from the tenant config section still apply to this batch exactly as for a normal run — a backfill batch is "a normal run, but pretending a different date is today".
- When writing the final report, clearly label it as a backfill batch for the given date so the orchestrator can tell child runs apart in history.

If the prompt does NOT contain a `## Backfill window` section, ignore everything in this subsection and run the skill normally with today's date. The default path is unchanged.

## STEP 0: VERIFY ENVIRONMENT

You are running inside Claude Code. The skill lives under `.claude/skills/zuora-demo-data-nightly/` within the project directory.

- **Zuora MCP server** is configured in the project's `.mcp.json`. Tool calls like `mcp__zuora-developer-mcp__query_objects`, `mcp__zuora-developer-mcp__create_subscriptions`, and `mcp__zuora-developer-mcp__cancel_subscriptions` MUST be available before you do any work.
- **Amendments and usage posts** are handled by the Python helper at `.claude/skills/zuora-demo-data-nightly/scripts/zuora_helpers.py`, invoked via the `Bash` tool. The helper uses the Zuora SDK and reads credentials from the environment variables `ZUORA_CLIENT_ID`, `ZUORA_CLIENT_SECRET`, and `ZUORA_ENVIRONMENT` (which are injected by the launcher script).
- **There is no browser.** Do NOT attempt to use `tabs_context_mcp`, `navigate`, `javascript_tool`, or any Chrome MCP tools.
- **DO NOT use `scripts/orchestrator.py` or `scripts/zuora_client.py`** under any circumstances. Those are legacy REST clients with known bugs (wrong field names on create/cancel/amend) and will produce broken data. They are kept on disk only for reference. The ONLY Python you should ever invoke from `Bash` is `scripts/zuora_helpers.py`.

**Pre-flight checks — both must pass before doing any work:**

1. Confirm the Zuora MCP tools are exposed. Try a tiny read query:
   ```
   mcp__zuora-developer-mcp__query_objects(objectType: "Accounts", pageSize: 1, fields: ["id"])
   ```
   If this tool call is not available (the function does not exist), or if it errors with an authentication failure, STOP IMMEDIATELY. Write a one-paragraph report to the output file explaining that the Zuora MCP server is not loaded, and exit. **Do not** attempt to fall back to `orchestrator.py`, `zuora_client.py`, or any direct REST calls — those code paths are broken and will silently produce invalid data.

2. Confirm the helper is reachable:
   ```bash
   python3 .claude/skills/zuora-demo-data-nightly/scripts/zuora_helpers.py --help 2>&1 | head -20
   ```
   If that fails because `zuora-sdk` is not installed, install it once with `pip install zuora-sdk` (drop `--break-system-packages` if your Python complains about it being an unknown option).

You do not need to read a credentials file — the helper auto-resolves credentials from the environment. To confirm the target tenant, `echo "$ZUORA_ENVIRONMENT"` is sufficient (should be `CSBX`).

## STEP 1: DISCOVER TENANT STATE

Use the Zuora MCP tools to understand what already exists.

### 1a. Pull the product catalog
```
query_objects(objectType: "ProductRatePlans", fields: ["id", "name", "productid"], pageSize: 50)
```

This query is a sanity check that the IDs in the prompt's **Tenant configuration → Products / Add-ons** section still resolve in the tenant. If any rate plan ID from the prompt is missing or renamed, log it in your final report and skip any action that depends on it — do not substitute values from anywhere else.

**The example IDs that used to appear here have been removed.** Use only what the prompt provides.

### 1b. Pull active subscriptions (to know what can be amended/cancelled)
```
query_objects(objectType: "Subscriptions", filter: ["status.EQ:Active", "islatestversion.EQ:true"], fields: ["id", "name", "accountid"], pageSize: 50)
```

### 1c. Pull active accounts
```
query_objects(objectType: "Accounts", filter: ["status.EQ:Active"], fields: ["id", "name", "accountnumber"], pageSize: 50)
```

## STEP 2: PLAN THE BATCH

Pull the volume ranges, tier mix, amendment mix, and growth bias from the prompt's **Tenant configuration** section. Randomly pick an action count within each min/max range.

**Data story rules (independent of any specific tenant):**
- New subs + upgrades + add-product should outnumber cancellations + downgrades + remove-product (growth trajectory). The growth-bias multiplier from the prompt tightens or widens this ratio but never flips it.
- Use the company-name prefixes and suffixes from the prompt's name pool to generate new account names. Combine randomly; avoid duplicates within the same run.
- Distribute new subscriptions across the product tiers according to the tier mix percentages in the prompt.
- Upgrades always move up exactly one tier. Downgrades always move down exactly one tier.
- Add-products pick a random add-on from the prompt's add-on list.
- Remove-products target subscriptions that already have an add-on attached.
- Random usage posts target subscriptions with usage-based charges (query `RatePlanCharges` to find `chargemodel: "Per Unit"`).

## STEP 3: EXECUTE ACTIONS

### 3a. New Subscriptions (via MCP `create_subscriptions`)

**CRITICAL — tested and verified payload pattern:**

```
create_subscriptions(
  mode: "create",
  orderDate: "<today YYYY-MM-DD>",
  newAccountJson: "{
    \"name\": \"<Company Name>\",
    \"currency\": \"USD\",
    \"billCycleDay\": <1-28 random>,
    \"billToContact\": {
      \"firstName\": \"<First>\",
      \"lastName\": \"<Last>\",
      \"workEmail\": \"<email>\",
      \"country\": \"US\",
      \"state\": \"CA\",
      \"city\": \"San Francisco\",
      \"address1\": \"<street address>\"
    },
    \"creditCard\": {
      \"cardType\": \"Visa\",
      \"cardNumber\": \"4111111111111111\",
      \"expirationMonth\": 12,
      \"expirationYear\": 2030,
      \"securityCode\": \"123\",
      \"cardHolderInfo\": {
        \"cardHolderName\": \"<First Last>\",
        \"addressLine1\": \"<street address>\",
        \"city\": \"San Francisco\",
        \"state\": \"CA\",
        \"country\": \"US\",
        \"zipCode\": \"94105\"
      }
    }
  }",
  createSubscriptionJson: "{
    \"subscribeToRatePlans\": [{\"productRatePlanId\": \"<rate-plan-id>\"}],
    \"terms\": {
      \"initialTerm\": {\"period\": 12, \"periodType\": \"Month\", \"termType\": \"TERMED\"},
      \"autoRenew\": true,
      \"renewalSetting\": \"RENEW_WITH_SPECIFIC_TERM\",
      \"renewalTerms\": [{\"period\": 12, \"periodType\": \"Month\"}]
    }
  }"
)
```

**IMPORTANT newAccount rules:**
- `billCycleDay` is REQUIRED — Zuora rejects the order without it
- Do NOT put `postalCode` in `billToContact` — it causes validation errors
- `zipCode` goes ONLY inside `creditCard.cardHolderInfo`
- `creditCard` is REQUIRED even in sandbox
- Use test card: Visa 4111111111111111, exp 12/2030, CVV 123
- Vary: company names, contact names, cities, states, billCycleDay (1-28)

**Company name generation:** Use realistic tech company names like:
- Apex Technologies, NovaBridge Software, Quantum Dynamics, Skyline Analytics
- DataVault Inc, CloudForge Solutions, PulsePoint Systems, Zenith Platforms
- ClearPath AI, BlueStar Networks, MetricWave, Streamline Digital
- TerraCore Labs, Ironclad Security, BrightLoop, VectorScale

### 3b. Cancellations (via MCP `cancel_subscriptions`)

```
cancel_subscriptions(
  subscriptionId: "<subscription-number e.g. A-S00000227>",
  cancellationPolicy: "EndOfCurrentTerm",
  orderDate: "<today YYYY-MM-DD>"
)
```

- Prefer EndOfCurrentTerm (more realistic than immediate)
- **Evergreen subscriptions** cannot use EndOfCurrentTerm — use `SpecificDate` with today's date instead:
  ```
  cancel_subscriptions(
    subscriptionId: "<subscription-number>",
    cancellationPolicy: "SpecificDate",
    cancellationEffectiveDate: "<today YYYY-MM-DD>",
    orderDate: "<today YYYY-MM-DD>"
  )
  ```
  If a cancellation fails with error 53200030, retry with SpecificDate policy.
- Only cancel subscriptions that have been active for a while (not ones just created this run)
- Target lower-tier subscriptions for cancellation more often (Basic > Pro > Enterprise)

### 3c. Amendments (via Bash → `zuora_helpers.py`)

Amendments are executed by shelling out to the Python helper, which calls the Zuora SDK's Orders API. Credentials come from the environment — no token management required.

**To get subscription rate plan IDs** (needed for RemoveProduct / ChangePlan), query via MCP:
```
query_objects(objectType: "RatePlans", filter: ["subscriptionid.EQ:<subscription-id>"], fields: ["id", "name", "productrateplanid"])
```
Note: use the subscription `id` (UUID), not the subscription number.

Each amendment below is a single `Bash` tool call. All three trigger dates (ContractEffective / ServiceActivation / CustomerAcceptance) and the current date are handled by the helper.

**Upgrade / Downgrade (swap rate plans) — `change-plan`:**
```bash
python3 .claude/skills/zuora-demo-data-nightly/scripts/zuora_helpers.py change-plan \
  --account "<account-number>" \
  --subscription "<subscription-number>" \
  --remove-rate-plan-id "<current-subscription-rate-plan-id>" \
  --add-product-rate-plan-id "<new-catalog-product-rate-plan-id>"
```

**Add product (e.g., Analytics add-on) — `add-product`:**
```bash
python3 .claude/skills/zuora-demo-data-nightly/scripts/zuora_helpers.py add-product \
  --account "<account-number>" \
  --subscription "<subscription-number>" \
  --product-rate-plan-id "<addon-catalog-product-rate-plan-id>"
```

**Remove product — `remove-product`:**
```bash
python3 .claude/skills/zuora-demo-data-nightly/scripts/zuora_helpers.py remove-product \
  --account "<account-number>" \
  --subscription "<subscription-number>" \
  --rate-plan-id "<subscription-rate-plan-id-to-remove>"
```

The helper prints a JSON result. `{"success": true, "order_number": "..."}` means the order succeeded; anything else is an error to log and move on from.

**IMPORTANT amendment notes:**
- `--remove-rate-plan-id` / `--rate-plan-id` is the **subscription rate plan ID** (from `query_objects` on RatePlans), not the product rate plan ID.
- `--add-product-rate-plan-id` / `--product-rate-plan-id` is the **catalog product rate plan ID** (from the catalog in Step 1a).
- If a call fails, log the helper's error output and continue with the next amendment — do not abort the run.

### 3d. Usage Posts (via Bash → `zuora_helpers.py`)

Usage is posted by calling the helper's `post-usage` subcommand, which in turn uses the Zuora SDK's Usage API.

To find the charge number for usage posting, query:
```
query_objects(objectType: "RatePlanCharges", filter: ["rateplanid.EQ:<rate-plan-id>"], fields: ["id", "chargenumber", "chargemodel", "uom"])
```
For the API-based demo usage, look for charges with `chargemodel: "Per Unit"` and UOM `"API Call"`.

```bash
python3 .claude/skills/zuora-demo-data-nightly/scripts/zuora_helpers.py post-usage \
  --account-number "<account-number>" \
  --subscription-number "<subscription-number>" \
  --charge-number "<charge-number>" \
  --uom "API Call" \
  --quantity <500-50000 random>
```

The helper prints a JSON result. `{"success": true, "id": "..."}` means the usage record was accepted.

**IMPORTANT usage notes:**
- UOM is a string and must match the charge's UOM exactly. For the random API Plan usage posts, that's `"API Call"` (singular) — not `"API Calls"`.
- Use `--account-number` (not account ID) unless you already have an account ID handy.
- The helper fills in `StartDateTime` as "now" in ISO format; you don't need to pass `--start-date` unless you want a specific date.
- Vary quantity realistically: 500–50,000.
- If a post fails, log the error and continue.

**MANDATORY usage posts — always post to every subscription listed in the prompt's `Mandatory usage subscriptions` section, in addition to the random usage posts above.**

These represent prepaid drawdown (PPDD) and minimum commit use cases and must receive usage activity every run so those demo stories stay current. The exact subscription numbers vary per tenant — use only what the prompt provides.

For each mandatory subscription, at runtime:

1. Resolve the subscription's active rate plan charges via MCP:
   ```
   query_objects(objectType: "Subscriptions", filter: ["name.EQ:<A-S0000035X>", "islatestversion.EQ:true"], fields: ["id", "accountid"])
   query_objects(objectType: "RatePlans", filter: ["subscriptionid.EQ:<sub-id>"], fields: ["id", "name"])
   query_objects(objectType: "RatePlanCharges", filter: ["rateplanid.EQ:<rate-plan-id>"], fields: ["id", "chargenumber", "chargemodel", "uom", "name"])
   ```
2. Pick the usage/drawdown charge — for PPDD this is the drawdown charge against the prepaid balance; for min-commit this is the usage charge that draws down the committed amount. Use whatever UOM the charge actually defines (don't assume "API Call").
3. Look up the account number from the account id:
   ```
   query_objects(objectType: "Accounts", filter: ["id.EQ:<account-id>"], fields: ["accountnumber"])
   ```
4. Post a usage record using the same `zuora_helpers.py post-usage` command shown above, setting `--uom` to the charge's actual UOM value (do **not** assume "API Call" for these subs). Use a realistic quantity (500–50,000).
5. If the usage post fails (e.g., the charge's UOM doesn't match, or the sub no longer has a drawdown charge), log the error and continue — do not let a failure on these mandatory posts stop the rest of the run.

These three mandatory posts are **in addition to** the 5-10 random usage posts and should be called out separately in the final report so it's clear the PPDD / min-commit scenarios received activity.

### STEP 3e: Apply Payments to Open Invoices

1. Check if the tenant config's `payments` section has `enabled: true`. If not, skip this step entirely.
2. Query posted invoices with open balances:
   ```
   query_objects(objectType: "Invoices", filter: ["balance.GT:0", "status.EQ:Posted"], fields: ["id", "invoicenumber", "invoicedate", "amount", "balance", "accountid"], pageSize: 50)
   ```
3. Randomly select a percentage of them based on the config's `pay_percentage` (min/max range, default 60–80%).
4. For each selected invoice:
   a. Look up the account's currency:
      ```
      query_objects(objectType: "Accounts", filter: ["id.EQ:<account-id>"], fields: ["currency"])
      ```
   b. Calculate payment date = invoice date + random(`payment_lag_days` min–max, default 1–5 days). For backfill runs, use the backfill date + lag days instead (not today).
   c. Create payment via Bash calling `zuora_helpers.py`:
      ```bash
      python3 .claude/skills/zuora-demo-data-nightly/scripts/zuora_helpers.py apply-payment \
        --account-id <account-id> \
        --invoice-id <invoice-id> \
        --amount <invoice-balance> \
        --currency <account-currency> \
        --effective-date <YYYY-MM-DD>
      ```
   d. The helper prints JSON on success: `{"success": true, "payment_number": "P-00000108", "amount": 1250.00}`
5. Log results for the report.
6. If no invoices are found, log "No open invoices found" and continue — don't treat it as an error.
7. If a payment fails, log the error and continue with the next one.

**IMPORTANT payment notes:**
- The helper uses External payment type (no gateway needed) and auto-discovers the tenant's WireTransfer/Cash payment method.
- Payment amount is always the full invoice balance (not partial).
- For backfill runs, the effective date should be the backfill date + lag days, not today.

### STEP 3f: Write Off Invoices via Credit Memo

1. Check if the tenant config's `writeoffs` section has `enabled: true`. If not, skip this step entirely.
2. Check the write-off frequency/cadence from config (`every_other_run` by default). For simplicity, the agent should decide probabilistically — ~50% chance of running write-offs on any given run.
3. Query oldest posted invoices with open balances, sorted by date ascending: same query as 3e but pick the oldest 1–2 invoices under the `max_invoice_amount` threshold (default $500).
4. For each selected invoice:
   a. Create credit memo and apply it via Bash calling `zuora_helpers.py`:
      ```bash
      python3 .claude/skills/zuora-demo-data-nightly/scripts/zuora_helpers.py create-credit-memo \
        --invoice-id <invoice-id> \
        --reason-code "Write-off" \
        --comment "Small balance write-off — demo data" \
        --apply
      ```
   b. The helper prints JSON on success: `{"success": true, "credit_memo_number": "CM00000005", "amount": 89.50, "applied": true}`
5. Log results for the report. Count should be 0–2 per run.

### Amendment & usage strategy:
- **Upgrades:** Basic→Pro or Pro→Enterprise. Query the sub's rate plans, remove the current one, add the higher-tier equivalent (Annual→Annual, Monthly→Monthly)
- **Add product:** Add Analytics or AI Insights to subs that don't already have them
- **Downgrade:** Enterprise→Pro or Pro→Basic (same swap pattern as upgrade, but lower tier)
- **Remove product:** Remove an add-on (Analytics or AI Insights) from subs that have them
- **Usage:** Post to subscriptions with API Plans (usage-based charges). Vary quantity: 500-50,000

## STEP 4: REPORT RESULTS

After completing all actions, produce a summary:

```
## Zuora Demo Data Run — <date>

### New Subscriptions: X created
| Account | Subscription | Product | Plan |
|---------|-------------|---------|------|
| ... | ... | ... | ... |

### Amendments: X completed
| Subscription | Type | Details |
|-------------|------|---------|
| ... | Upgrade | Basic Annual → Pro Annual |
| ... | Add Product | Added Analytics |

### Cancellations: X processed
| Subscription | Account | Policy |
|-------------|---------|--------|
| ... | ... | EndOfCurrentTerm |

### Usage Posted: X records
| Subscription | Charge | Quantity | UOM |
|-------------|--------|----------|-----|
| ... | ... | 12,500 | API Calls |

### Payments Applied: X processed
| Invoice | Account | Amount | Payment Date | Payment # |
|---------|---------|--------|-------------|-----------|
| INV00000042 | Apex Technologies | $1,250.00 | 2026-04-12 | P-00000108 |

### Write-offs: X processed
| Invoice | Account | Amount | Credit Memo # | Reason |
|---------|---------|--------|--------------|--------|
| INV00000018 | DataVault Inc | $89.50 | CM00000005 | Small balance write-off |

### Data Story Health
- New + Upgrades: X | Cancellations + Downgrades: Y | Net Growth: +Z
```

If any action fails, log the error and continue with the remaining actions. Do not let one failure stop the entire batch.