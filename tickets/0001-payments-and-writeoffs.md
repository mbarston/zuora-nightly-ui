# TICKET-0001: Payments & Invoice Write-offs

| Field | Value |
|-------|-------|
| **Status** | `draft` |
| **Priority** | High |
| **Author** | Matt Barston |
| **Created** | 2026-04-10 |
| **Estimated effort** | Medium (2-3 sessions) |

---

## Problem Statement

The demo data skill currently creates subscriptions, amendments, cancellations, and usage — but never touches the **billing and collections** side of Zuora. This means sandbox tenants have:

- Invoices sitting with open balances (no payments applied)
- No credit memo / write-off activity
- AR aging reports that look unrealistic (everything is unpaid)

For SEs demoing Zuora's billing, payments, or collections workflows, this is a gap. A realistic tenant should show:

1. **Most invoices are paid** — payments applied within a few days of invoice generation
2. **A few invoices are written off** — small credit memos zeroing out old/disputed invoices every couple of weeks
3. **Some invoices remain open** — a realistic AR aging tail (30/60/90 day buckets)

---

## Proposed Solution

Add two new action categories to the nightly skill run:

### Action 1: Apply Payments to Open Invoices

Each run, find invoices with open balances and apply payments to a subset of them.

**Logic:**
- Query `Invoices` with `balance.GT:0` and `status.EQ:Posted`
- Pay 60-80% of the open invoices found (configurable via tenant config)
- Payment amount = invoice balance (full payment, not partial)
- Payment method: use the account's default payment method (already on file from subscription creation — Visa test card)
- Payment date: invoice date + 1-5 days (randomized, to simulate realistic payment lag)

**Zuora API approach:**
- The MCP server does NOT have a dedicated `create_payment` tool
- **Option A**: Add `apply-payment` subcommand to `zuora_helpers.py` using the Zuora SDK's `PaymentsApi.create_payment()` method
- **Option B**: Use the Zuora REST API directly via `httpx` in the helper (`POST /v1/object/payment` or `POST /v1/payments`)
- Recommend **Option A** (SDK) for consistency with existing amendment/usage helpers

**Payment payload (via Zuora SDK):**
```python
{
    "AccountId": "<account-id>",
    "Amount": <invoice-balance>,
    "Currency": "USD",
    "EffectiveDate": "<invoice-date + 1-5 days>",
    "PaymentMethodId": "<default-payment-method-id>",
    "Type": "Electronic",
    "Status": "Processed",
    "InvoiceId": "<invoice-id>"  # or use applied_to for Invoice Settlement
}
```

**For tenants with Invoice Settlement enabled (most modern sandboxes):**
- Create the payment first, then apply it to the invoice via a payment application
- Or use the `POST /v1/payments` endpoint which supports `invoices` array for automatic application

### Action 2: Write Off Invoices via Credit Memo

Every other run (or based on a configurable cadence), write off 1-2 small invoices.

**Logic:**
- Query invoices with `balance.GT:0`, sorted by `invoiceDate` ascending (oldest first)
- Pick 1-2 invoices, preferring older and smaller balances
- Create a credit memo for the full invoice amount
- Apply the credit memo to the invoice to zero it out

**Zuora API approach:**
- Add `create-credit-memo` subcommand to `zuora_helpers.py`
- Use `POST /v1/creditmemos` to create the credit memo from the invoice
- Then `POST /v1/creditmemos/{id}/apply` to apply it to the target invoice
- Or use `POST /v1/object/credit-memo` depending on tenant API version

**Credit memo payload:**
```python
# Create credit memo from invoice
POST /v1/creditmemos
{
    "invoiceId": "<invoice-id>",
    "reasonCode": "Write-off",
    "comment": "Small balance write-off — demo data"
}

# Apply credit memo to invoice
POST /v1/creditmemos/{creditMemoId}/apply
{
    "invoices": [{
        "invoiceId": "<invoice-id>",
        "amount": <credit-memo-amount>
    }]
}
```

---

## Tenant Configuration Changes

Add a new section to the tenant config schema:

```json
{
    "payments": {
        "enabled": true,
        "pay_percentage": { "min": 60, "max": 80 },
        "payment_lag_days": { "min": 1, "max": 5 }
    },
    "writeoffs": {
        "enabled": true,
        "frequency": "every_other_run",
        "count": { "min": 1, "max": 2 },
        "max_invoice_amount": 500.00
    }
}
```

**Config editor UI additions:**
- New "Payments & Write-offs" section on the TenantConfigPage
- Toggle to enable/disable each action
- Sliders or min/max inputs for pay percentage, lag days, write-off count
- Max invoice amount threshold for write-offs (don't write off large invoices)

---

## SKILL.md Changes

Add new steps to the skill definition:

### STEP 3e: Apply Payments (new)

After creating subscriptions, amendments, cancellations, and usage:

1. Query posted invoices with open balances
2. Randomly select 60-80% of them (per config)
3. For each selected invoice:
   a. Look up the account's default payment method
   b. Calculate payment date = invoice date + random(1-5) days
   c. Create and apply payment via `zuora_helpers.py apply-payment`
4. Log results for the report

### STEP 3f: Write Off Invoices (new)

Based on cadence (every other run by default):

1. Query oldest posted invoices with small open balances
2. Pick 1-2 invoices under the max amount threshold
3. For each selected invoice:
   a. Create credit memo from invoice via `zuora_helpers.py create-credit-memo`
   b. Apply credit memo to zero out the balance
4. Log results for the report

### STEP 4: Report (updated)

Add two new sections to the run report:

```markdown
### Payments Applied: X processed
| Invoice | Account | Amount | Payment Date | Payment # |
|---------|---------|--------|-------------|-----------|
| INV00000042 | Apex Technologies | $1,250.00 | 2026-04-12 | P-00000108 |

### Write-offs: X processed
| Invoice | Account | Amount | Credit Memo # | Reason |
|---------|---------|--------|--------------|--------|
| INV00000018 | DataVault Inc | $89.50 | CM00000005 | Small balance write-off |
```

---

## zuora_helpers.py Changes

Add two new subcommands:

### `apply-payment`

```
python3 zuora_helpers.py apply-payment \
  --account-id <account-id> \
  --invoice-id <invoice-id> \
  --amount <amount> \
  --payment-method-id <payment-method-id> \
  --effective-date <YYYY-MM-DD>
```

Returns: `{"success": true, "payment_number": "P-00000108", "amount": 1250.00}`

### `create-credit-memo`

```
python3 zuora_helpers.py create-credit-memo \
  --invoice-id <invoice-id> \
  --reason-code "Write-off" \
  --comment "Small balance write-off — demo data" \
  --apply
```

The `--apply` flag creates the credit memo AND applies it to the source invoice in one step.

Returns: `{"success": true, "credit_memo_number": "CM00000005", "amount": 89.50, "applied": true}`

---

## Implementation Plan

### Phase 1: Backend — zuora_helpers.py (Day 1)

1. Add `apply-payment` subcommand
   - Use Zuora SDK `PaymentsApi` or REST `POST /v1/payments`
   - Support Invoice Settlement flow (create payment + apply to invoice)
   - Handle errors gracefully (insufficient balance, invalid payment method, etc.)
2. Add `create-credit-memo` subcommand
   - Create credit memo from invoice
   - Optionally auto-apply to zero out the invoice balance
   - Support reason codes
3. Test both commands manually against a sandbox

### Phase 2: Skill — SKILL.md (Day 1)

1. Add STEP 3e (payments) and STEP 3f (write-offs) to SKILL.md
2. Update STEP 4 (report) with new sections
3. Add backfill-aware date handling (payments should use backfill date + lag, not today)

### Phase 3: Config — Tenant Configuration (Day 2)

1. Add `payments` and `writeoffs` sections to config schema
2. Add default values in `seed_default_config()`
3. Add validation rules
4. Update `to_prompt_markdown()` to serialize the new config sections
5. Update config editor UI with new section

### Phase 4: Test & Deploy (Day 2)

1. Run locally against a sandbox with existing invoices
2. Verify payments show up in Zuora UI (Billing > Payments)
3. Verify credit memos show up and invoices are zeroed out
4. Deploy to Fly.io

---

## Edge Cases & Risks

| Risk | Mitigation |
|------|-----------|
| No posted invoices exist yet (new tenant) | Skip payments/write-offs gracefully, note in report |
| Account has no default payment method | Skip that invoice, log warning |
| Invoice Settlement not enabled on tenant | Detect via API response; fall back to legacy payment flow |
| Credit memo reason code doesn't exist in tenant | Use a safe default or skip; log the error |
| Backfill runs: payment dates must be backdated | Use backfill date + lag days, not today |
| Write-off cadence tracking across runs | Use run count modulo 2, or add a tenant-level counter |
| Payment gateway rejects test card in certain sandboxes | Catch gateway errors, skip gracefully |

---

## Success Criteria

- [ ] Running the skill on a tenant with posted invoices results in 60-80% of them being paid
- [ ] Every other run produces 1-2 credit memo write-offs on old/small invoices
- [ ] Payment and write-off activity appears correctly in Zuora UI
- [ ] AR aging in Zuora shows a realistic distribution (most current, some 30-day, few 60-day)
- [ ] The run report includes payment and write-off sections
- [ ] Config editor has a working Payments & Write-offs section
- [ ] Backfill runs correctly backdate payment and write-off timestamps
