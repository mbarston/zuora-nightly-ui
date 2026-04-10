# TICKET-0001: Payments & Invoice Write-offs

| Field | Value |
|-------|-------|
| **Status** | `draft` |
| **Priority** | High |
| **Author** | Matt Barston |
| **Created** | 2026-04-10 |
| **Estimated effort** | Large (4-5 sessions) |

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

---

## Part B: Standalone Billing & Payments UI

In addition to the automated skill-run integration (Part A above), add a dedicated **Billing & Payments** page per tenant that gives SEs hands-on control over the billing-to-cash cycle. This is used for ad-hoc demo prep — run a bill run, review what invoices came out, and selectively apply payments.

### New Route: `/tenants/{tenantId}/billing`

Accessible from the tenant card on the dashboard via a new **Billing** button (banknote/dollar icon).

### Page Layout

The page has three sequential workflow sections, each unlocking the next:

---

#### Section 1: Bill Run

A card at the top that lets you trigger an ad-hoc bill run in Zuora.

**UI:**
```
┌─────────────────────────────────────────────────────────┐
│  Bill Run                                               │
│                                                         │
│  Target date:  [ 2026-04-10 ]    ┌──────────────────┐   │
│                                  │  Run Billing  ▶   │   │
│                                  └──────────────────┘   │
│                                                         │
│  Status: ● Completed — 23 invoices generated (4.2s)     │
│  Last run: 2026-04-10 12:45 UTC                         │
└─────────────────────────────────────────────────────────┘
```

**Behavior:**
- **Target date** input defaults to today
- **Run Billing** button triggers `POST /v1/object/bill-run` via a new backend endpoint
- Bill runs are async in Zuora — the UI polls for completion status (Pending → Processing → Completed/Error)
- Shows a spinner + progress state while running
- On completion, shows invoice count and elapsed time
- Automatically triggers the invoice import in Section 2

**Backend endpoint:**
- `POST /api/tenants/{tenantId}/billing/run` — Creates a bill run via Zuora REST API (`POST /v1/object/bill-run` with `InvoiceDate`, `TargetDate`, `Status: "Pending"`)
- `GET /api/tenants/{tenantId}/billing/run-status/{billRunId}` — Polls status until terminal
- Uses tenant's OAuth credentials (same pattern as skill runs)
- Implemented in `zuora_helpers.py` with new `bill-run` subcommand, or directly in a new `backend/app/billing.py` module using `httpx`

---

#### Section 2: Open Invoices

After a bill run completes (or on page load), fetch and display all open invoices.

**UI:**
```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  Open Invoices (23)                                    [ Refresh ]  [ Select All ]  │
│                                                                                     │
│  ☐  Invoice #       Account              Date         Amount      Balance    Age    │
│  ─────────────────────────────────────────────────────────────────────────────────   │
│  ☑  INV00000042     Apex Technologies     2026-04-01   $1,250.00   $1,250.00  9d    │
│  ☑  INV00000041     NovaBridge Software   2026-04-01   $3,400.00   $3,400.00  9d    │
│  ☐  INV00000039     CloudForge Solutions  2026-03-15   $890.00     $445.00    26d   │
│  ☑  INV00000038     Quantum Dynamics      2026-03-01   $2,100.00   $2,100.00  40d   │
│  ☐  INV00000035     Zenith Platforms      2026-02-15   $156.50     $156.50    54d   │
│  ...                                                                                │
│                                                                                     │
│  Selected: 3 invoices · Total: $6,750.00                                            │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- **Import/Refresh** button queries Zuora: `query_objects(objectType: "Invoices", filter: ["balance.GT:0", "status.EQ:Posted"], fields: [...])`
- Table shows invoice number, account name, invoice date, total amount, open balance, and aging (days since invoice date)
- Sortable columns (by date, amount, balance, age)
- Search/filter bar to filter by account name or invoice number
- **Checkboxes** for selecting which invoices to pay
- **Select All / Deselect All** toggle
- Footer shows selected count and total balance of selected invoices

**Backend endpoint:**
- `GET /api/tenants/{tenantId}/billing/open-invoices` — Queries Zuora for posted invoices with balance > 0, enriches with account names

---

#### Section 3: Apply Payments

Once invoices are selected, this section appears/expands to let you configure and submit payments.

**UI:**
```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  Apply Payments                                                                     │
│                                                                                     │
│  Payment date:  [ 2026-04-10 ]                                                      │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐     │
│  │  Invoice          Account              Balance       Pay Amount            │     │
│  │  ────────────────────────────────────────────────────────────────────────   │     │
│  │  INV00000042      Apex Technologies     $1,250.00     [ $1,250.00 ]  [Full]│     │
│  │  INV00000041      NovaBridge Software   $3,400.00     [ $3,400.00 ]  [Full]│     │
│  │  INV00000038      Quantum Dynamics      $2,100.00     [ $1,000.00 ]        │     │
│  └─────────────────────────────────────────────────────────────────────────────┘     │
│                                                                                     │
│  Total payment: $5,650.00                                                           │
│                                                                                     │
│  ┌─────────────────────────────┐                                                    │
│  │  Apply Payments (3)    💳   │                                                    │
│  └─────────────────────────────┘                                                    │
│                                                                                     │
│  Results:                                                                           │
│   ✓ INV00000042 — P-00000108 — $1,250.00                                            │
│   ✓ INV00000041 — P-00000109 — $3,400.00                                            │
│   ✓ INV00000038 — P-00000110 — $1,000.00 (partial, $1,100.00 remaining)             │
│                                                                                     │
│  3/3 payments applied · Total: $5,650.00                                            │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- **Payment date** input defaults to today, shared across all payments
- Each selected invoice shows its open balance and an **editable payment amount** field
  - Defaults to full balance
  - **[Full]** button resets to full balance
  - User can type a partial amount (must be > 0 and <= balance)
- **Apply Payments** button submits all payments serially
- Results stream in row by row as each payment succeeds/fails
- Shows payment number, amount applied, and remaining balance (if partial)
- Failed payments show error inline (red) but don't stop the batch
- After completion, the invoice list in Section 2 auto-refreshes to show updated balances

**Backend endpoint:**
- `POST /api/tenants/{tenantId}/billing/apply-payments` — Accepts array of `{invoiceId, accountId, amount, paymentMethodId, effectiveDate}`, processes sequentially, returns results array

**Zuora API flow per payment:**
1. Look up account's default payment method via `query_objects(objectType: "PaymentMethods", filter: ["accountid.EQ:{accountId}", "isdefault.EQ:true"])`
2. Create payment via `POST /v1/payments`:
   ```json
   {
     "AccountId": "<account-id>",
     "Amount": <pay-amount>,
     "Currency": "USD",
     "EffectiveDate": "<payment-date>",
     "PaymentMethodId": "<default-payment-method-id>",
     "Type": "Electronic",
     "InvoiceId": "<invoice-id>"
   }
   ```
   Or for Invoice Settlement tenants, use the `invoices` array in the payment body.
3. Return payment number + status

---

### Dashboard Integration

Add a **Billing** button to each tenant card on the dashboard (between Chat and Configure):

```
[ Run now ▶ ]  [ Backfill 📅 ]  [ Chat 💬 ]  [ Billing 💳 ]  [ Configure ⚙ ]  [ Edit ✏ ]  [ Delete 🗑 ]
```

---

### Write-Off Tab (future enhancement)

The billing page could later add a second tab for write-offs:
- Show invoices with small balances or old aging (60+ days)
- Select invoices to write off
- Create credit memos and apply them in one click
- For now, write-offs remain in the automated skill run (Part A)

---

## Updated Implementation Plan

### Phase 1: Backend — Zuora API Layer (Day 1)

New module: `backend/app/billing.py` — direct Zuora REST API calls using `httpx` with OAuth.

1. `create_bill_run(tenant, target_date)` — `POST /v1/object/bill-run`
2. `get_bill_run_status(tenant, bill_run_id)` — `GET /v1/object/bill-run/{id}`
3. `get_open_invoices(tenant)` — `query_objects` via MCP or direct REST query
4. `apply_payment(tenant, invoice_id, account_id, amount, effective_date)` — `POST /v1/payments`
5. `create_credit_memo(tenant, invoice_id, reason_code)` — `POST /v1/creditmemos` + apply

Also add to `zuora_helpers.py`:
- `apply-payment` subcommand (for skill runs)
- `create-credit-memo` subcommand (for skill runs)

### Phase 2: Billing API Routes (Day 2)

New routes in `backend/app/routers/api/core.py`:

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/tenants/{id}/billing/run` | Trigger ad-hoc bill run |
| `GET` | `/api/tenants/{id}/billing/run-status/{billRunId}` | Poll bill run status |
| `GET` | `/api/tenants/{id}/billing/open-invoices` | Fetch open invoices |
| `POST` | `/api/tenants/{id}/billing/apply-payments` | Apply payments to selected invoices |

### Phase 3: Billing Page UI (Day 2-3)

New page: `frontend/src/pages/BillingPage.tsx`

1. Section 1 — Bill Run card (target date picker, run button, status polling)
2. Section 2 — Open Invoices table (checkbox selection, sortable, searchable)
3. Section 3 — Apply Payments panel (editable amounts, payment date, submit + results)
4. Add route `/tenants/:tenantId/billing` to App.tsx
5. Add Billing button to DashboardPage tenant cards

### Phase 4: Skill Integration — SKILL.md (Day 3)

1. Add STEP 3e (automated payments) and STEP 3f (write-offs) to SKILL.md
2. Update STEP 4 (report) with new sections
3. Add backfill-aware date handling (payments use backfill date + lag, not today)

### Phase 5: Config (Day 4)

1. Add `payments` and `writeoffs` sections to tenant config schema
2. Add default values in `seed_default_config()`
3. Add validation rules
4. Update `to_prompt_markdown()` to serialize the new config sections
5. Update config editor UI with new "Payments & Write-offs" section

### Phase 6: Test & Deploy (Day 4-5)

1. Test billing page locally against a sandbox
2. Verify bill run creates invoices in Zuora
3. Verify payments show up in Zuora UI (Billing > Payments)
4. Test partial payments and edge cases
5. Run skill with automated payments/write-offs enabled
6. Deploy to Fly.io

---

## Edge Cases & Risks

| Risk | Mitigation |
|------|-----------|
| No posted invoices exist yet (new tenant) | Skip payments/write-offs gracefully, note in report; billing page shows empty state |
| Account has no default payment method | Skip that invoice in automation; show warning icon in billing UI |
| Invoice Settlement not enabled on tenant | Detect via API response; fall back to legacy payment flow |
| Credit memo reason code doesn't exist in tenant | Use a safe default or skip; log the error |
| Backfill runs: payment dates must be backdated | Use backfill date + lag days, not today |
| Write-off cadence tracking across runs | Use run count modulo 2, or add a tenant-level counter |
| Payment gateway rejects test card in certain sandboxes | Catch gateway errors, skip gracefully; show error inline in billing UI |
| Bill run takes a long time on large tenants | Poll with timeout (5 min max); show elapsed time in UI |
| Bill run fails (no billable charges) | Handle Zuora error response gracefully; show "No charges to bill" message |
| Partial payment leaves small remaining balance | Show remaining balance in results; don't auto-write-off from the UI |
| User navigates away during bill run | Bill run continues in Zuora regardless; status resumes on return |
| Concurrent bill runs on same tenant | Zuora rejects concurrent bill runs; disable button while one is in progress |
| OAuth token expires during long invoice list | Auto-refresh token in httpx client; retry on 401 |

---

## Success Criteria

### Part A — Automated (Skill Runs)
- [ ] Running the skill on a tenant with posted invoices results in 60-80% of them being paid
- [ ] Every other run produces 1-2 credit memo write-offs on old/small invoices
- [ ] Payment and write-off activity appears correctly in Zuora UI
- [ ] AR aging in Zuora shows a realistic distribution (most current, some 30-day, few 60-day)
- [ ] The run report includes payment and write-off sections
- [ ] Config editor has a working Payments & Write-offs section
- [ ] Backfill runs correctly backdate payment and write-off timestamps

### Part B — Interactive (Billing Page)
- [ ] Billing page loads at `/tenants/{id}/billing` with three workflow sections
- [ ] Bill Run: clicking "Run Billing" triggers a real bill run in Zuora, polls for completion, shows invoice count
- [ ] Open Invoices: table loads all posted invoices with balance > 0, with correct aging calculation
- [ ] Open Invoices: table is sortable by date, amount, balance, age
- [ ] Open Invoices: search/filter works by account name or invoice number
- [ ] Open Invoices: checkbox selection with Select All / Deselect All and running total
- [ ] Apply Payments: selected invoices appear with editable amount fields defaulting to full balance
- [ ] Apply Payments: partial amounts accepted (validated > 0 and <= balance)
- [ ] Apply Payments: [Full] button resets amount to full balance
- [ ] Apply Payments: shared payment date picker defaults to today
- [ ] Apply Payments: clicking "Apply Payments" processes sequentially, streams results
- [ ] Apply Payments: failed payments show error inline but don't stop the batch
- [ ] Apply Payments: invoice list auto-refreshes after all payments complete
- [ ] Billing button appears on dashboard tenant cards
