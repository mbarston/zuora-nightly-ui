"""
Zuora Billing & Payments — direct REST API calls for the interactive
billing page (TICKET-0001 Part B).

This module talks to Zuora's REST API via httpx, handling OAuth token
management, bill runs, invoice queries, and payment application.

Unlike the skill runner (which delegates to the Claude Agent SDK + MCP),
these calls are made directly from the backend so the UI can drive them
interactively without spinning up a full agent session.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.crypto import decrypt
from app.models import Tenant

logger = logging.getLogger("zuora-se-agent.billing")

# ---------------------------------------------------------------------------
# OAuth token management
# ---------------------------------------------------------------------------

# In-memory token cache keyed by tenant_id → (token, expires_at).
# Good enough for a single-process server; tokens last ~1 hour.
_token_cache: dict[int, tuple[str, datetime]] = {}


async def _get_token(tenant: Tenant, client: httpx.AsyncClient) -> str:
    """Get a valid OAuth bearer token for the tenant, refreshing if needed."""
    cached = _token_cache.get(tenant.id)
    if cached:
        token, expires_at = cached
        # Refresh 60s early to avoid edge-case expiry mid-request
        if datetime.now(timezone.utc) < expires_at:
            return token

    client_secret = decrypt(tenant.client_secret_encrypted)
    resp = await client.post(
        f"{tenant.base_url}/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": tenant.client_id,
            "client_secret": client_secret,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    expires_in = data.get("expires_in", 3600)
    from datetime import timedelta
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
    _token_cache[tenant.id] = (token, expires_at)
    return token


def _clear_token_cache(tenant_id: int) -> None:
    """Evict cached token (e.g., on 401 retry)."""
    _token_cache.pop(tenant_id, None)


async def _authed_request(
    tenant: Tenant,
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    retry_on_401: bool = True,
) -> httpx.Response:
    """Make an authenticated request to the Zuora REST API."""
    token = await _get_token(tenant, client)
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{tenant.base_url}{path}"

    resp = await client.request(method, url, headers=headers, json=json, params=params)

    # Retry once on 401 (token may have expired between cache check and use)
    if resp.status_code == 401 and retry_on_401:
        _clear_token_cache(tenant.id)
        token = await _get_token(tenant, client)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.request(method, url, headers=headers, json=json, params=params)

    return resp


# ---------------------------------------------------------------------------
# Bill Run
# ---------------------------------------------------------------------------


async def create_bill_run(
    tenant: Tenant,
    target_date: date,
    invoice_date: date | None = None,
) -> dict[str, Any]:
    """
    Create an ad-hoc bill run in Zuora.

    Returns the bill run object with id and status.
    Zuora processes bill runs asynchronously — caller should poll
    get_bill_run_status() until status is Completed or Error.
    """
    if invoice_date is None:
        invoice_date = target_date

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await _authed_request(
            tenant, client, "POST", "/v1/object/bill-run",
            json={
                "InvoiceDate": invoice_date.isoformat(),
                "TargetDate": target_date.isoformat(),
            },
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("Success", True):
            errors = data.get("Errors", [])
            msg = "; ".join(e.get("Message", str(e)) for e in errors) if errors else str(data)
            raise BillingError(f"Failed to create bill run: {msg}")

        bill_run_id = data.get("Id")
        logger.info("Created bill run %s for tenant %s (target=%s)", bill_run_id, tenant.name, target_date)

        # Immediately post the bill run to start processing
        post_resp = await _authed_request(
            tenant, client, "PUT", f"/v1/object/bill-run/{bill_run_id}",
            json={"Status": "Posted"},
        )
        post_resp.raise_for_status()

        return {"id": bill_run_id, "status": "Posted"}


async def get_bill_run_status(tenant: Tenant, bill_run_id: str) -> dict[str, Any]:
    """Poll the status of a bill run."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await _authed_request(
            tenant, client, "GET", f"/v1/object/bill-run/{bill_run_id}",
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "id": bill_run_id,
            "status": data.get("Status", "Unknown"),
            "invoices_generated": data.get("NumberOfInvoices", 0),
            "credit_memos_generated": data.get("NumberOfCreditMemos", 0),
            "errors": data.get("NumberOfErrors", 0),
            "created_date": data.get("CreatedDate"),
        }


# ---------------------------------------------------------------------------
# Open Invoices
# ---------------------------------------------------------------------------


async def get_open_invoices(tenant: Tenant) -> list[dict[str, Any]]:
    """
    Fetch all posted invoices with a positive balance.

    Returns a list of invoice dicts enriched with account name and aging.
    """
    async with httpx.AsyncClient(timeout=120) as client:
        # Query invoices with balance > 0
        invoices = await _query_objects(
            tenant, client,
            object_type="Invoices",
            filters=["balance.GT:0", "status.EQ:Posted"],
            fields=["id", "invoicenumber", "invoicedate", "amount", "balance", "accountid", "duedate"],
            page_size=99,
        )

        if not invoices:
            return []

        # Collect unique account IDs and batch-fetch account names + currency
        account_ids = list({inv["AccountId"] for inv in invoices if inv.get("AccountId")})
        account_map: dict[str, dict[str, str]] = {}
        for account_id in account_ids:
            accounts = await _query_objects(
                tenant, client,
                object_type="Accounts",
                filters=[f"id.EQ:{account_id}"],
                fields=["id", "name", "accountnumber", "currency"],
                page_size=1,
            )
            if accounts:
                account_map[account_id] = {
                    "name": accounts[0].get("Name", "Unknown"),
                    "currency": accounts[0].get("Currency", "USD"),
                }

        today = date.today()
        result = []
        for inv in invoices:
            inv_date_str = inv.get("InvoiceDate", "")
            try:
                inv_date = datetime.fromisoformat(inv_date_str.replace("Z", "+00:00")).date()
            except (ValueError, AttributeError):
                inv_date = today
            age_days = (today - inv_date).days

            account_id = inv.get("AccountId", "")
            acct_info = account_map.get(account_id, {"name": "Unknown", "currency": "USD"})
            result.append({
                "id": inv.get("Id", ""),
                "invoice_number": inv.get("InvoiceNumber", ""),
                "invoice_date": inv_date.isoformat(),
                "amount": float(inv.get("Amount", 0)),
                "balance": float(inv.get("Balance", 0)),
                "account_id": account_id,
                "account_name": acct_info["name"],
                "currency": acct_info["currency"],
                "due_date": inv.get("DueDate", ""),
                "age_days": age_days,
            })

        # Sort by invoice date descending (newest first)
        result.sort(key=lambda x: x["invoice_date"], reverse=True)
        return result


# ---------------------------------------------------------------------------
# Apply Payment
# ---------------------------------------------------------------------------


# Cache: tenant_id → generic external-compatible payment method ID
_ext_pm_cache: dict[int, str] = {}


async def _get_external_payment_method_id(
    tenant: Tenant,
    client: httpx.AsyncClient,
) -> str:
    """
    Find the tenant's generic external-compatible payment method.

    Zuora tenants have system-level payment method types (no AccountId)
    that can be used for external payments. We look for WireTransfer, Cash,
    Check, or Other — any of these work with Type=External payments.
    """
    if tenant.id in _ext_pm_cache:
        return _ext_pm_cache[tenant.id]

    # Query all system-level payment methods (those without an AccountId).
    # We fetch a broad set and filter in Python since ZOQL doesn't support
    # IS NULL or empty-string matching reliably for AccountId.
    resp = await _authed_request(
        tenant, client, "POST", "/v1/action/query",
        json={
            "queryString": (
                "SELECT Id, Type, AccountId FROM PaymentMethod "
                "WHERE Type = 'WireTransfer' LIMIT 5"
            ),
        },
    )
    data = resp.json()
    # Filter to only system-level (no AccountId)
    records = [r for r in data.get("records", []) if not r.get("AccountId")]

    if not records:
        # Fallback: try Cash, Check, Other
        for pm_type in ("Cash", "Check", "Other"):
            resp2 = await _authed_request(
                tenant, client, "POST", "/v1/action/query",
                json={
                    "queryString": (
                        f"SELECT Id, Type, AccountId FROM PaymentMethod "
                        f"WHERE Type = '{pm_type}' LIMIT 5"
                    ),
                },
            )
            data2 = resp2.json()
            records = [r for r in data2.get("records", []) if not r.get("AccountId")]
            if records:
                break

    if not records:
        raise BillingError(
            "No external-compatible payment method found in this tenant. "
            "Check Z-Payments Settings."
        )

    pm_id = records[0]["Id"]
    _ext_pm_cache[tenant.id] = pm_id
    logger.info("Using payment method %s (type=%s) for tenant %d", pm_id, records[0].get("Type"), tenant.id)
    return pm_id


async def apply_payment(
    tenant: Tenant,
    *,
    account_id: str,
    invoice_id: str,
    amount: float,
    effective_date: date,
    currency: str = "USD",
) -> dict[str, Any]:
    """
    Create an external payment and apply it to an invoice.

    Uses a two-step approach:
      1. POST /v1/object/payment — creates the payment with a generic
         external-compatible payment method
      2. POST /v1/object/invoice-payment — applies it to the invoice
    """
    async with httpx.AsyncClient(timeout=60) as client:
        # Find the tenant's generic external-compatible payment method
        pm_id = await _get_external_payment_method_id(tenant, client)

        # Use POST /v1/payments (camelCase) which supports the invoices
        # array for automatic application in a single call.
        resp = await _authed_request(
            tenant, client, "POST", "/v1/payments",
            json={
                "accountId": account_id,
                "paymentMethodId": pm_id,
                "amount": amount,
                "currency": currency,
                "effectiveDate": effective_date.isoformat(),
                "type": "External",
                "invoices": [
                    {
                        "invoiceId": invoice_id,
                        "amount": amount,
                    }
                ],
            },
        )

        data = resp.json()

        if resp.status_code >= 400 or not data.get("success", data.get("Success", True)):
            reasons = data.get("reasons", data.get("Reasons", []))
            if reasons:
                msg = "; ".join(r.get("message", str(r)) for r in reasons)
            else:
                msg = data.get("message", data.get("Message", str(data)))
            raise BillingError(f"Payment failed: {msg}")

        return {
            "success": True,
            "payment_id": data.get("id", data.get("Id", "")),
            "payment_number": data.get("paymentNumber", data.get("PaymentNumber", "")),
            "amount": amount,
            "status": data.get("status", data.get("Status", "Processed")),
        }


# ---------------------------------------------------------------------------
# Credit Memo (write-off)
# ---------------------------------------------------------------------------


async def create_write_off(
    tenant: Tenant,
    *,
    invoice_id: str,
    amount: float,
    reason_code: str = "Write-off",
    comment: str = "Small balance write-off — demo data",
) -> dict[str, Any]:
    """
    Create a credit memo from an invoice and apply it to zero out
    (or reduce) the balance.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        # Create credit memo from invoice
        resp = await _authed_request(
            tenant, client, "POST", "/v1/creditmemos",
            json={
                "InvoiceId": invoice_id,
                "ReasonCode": reason_code,
                "Comment": comment,
            },
        )

        data = resp.json()
        if resp.status_code >= 400:
            msg = data.get("message", str(data))
            raise BillingError(f"Credit memo creation failed: {msg}")

        cm_id = data.get("id", "")
        cm_number = data.get("number", "")
        cm_amount = float(data.get("amount", amount))

        # Post the credit memo
        post_resp = await _authed_request(
            tenant, client, "PUT", f"/v1/creditmemos/{cm_id}/post",
            json={},
        )
        if post_resp.status_code >= 400:
            logger.warning("Failed to post credit memo %s: %s", cm_number, post_resp.text)

        # Apply credit memo to invoice
        apply_resp = await _authed_request(
            tenant, client, "POST", f"/v1/creditmemos/{cm_id}/apply",
            json={
                "invoices": [{
                    "invoiceId": invoice_id,
                    "amount": cm_amount,
                }]
            },
        )

        applied = apply_resp.status_code < 400
        if not applied:
            logger.warning("Failed to apply credit memo %s: %s", cm_number, apply_resp.text)

        return {
            "success": True,
            "credit_memo_id": cm_id,
            "credit_memo_number": cm_number,
            "amount": cm_amount,
            "applied": applied,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class BillingError(Exception):
    """Raised when a Zuora billing operation fails."""
    pass


async def _query_objects(
    tenant: Tenant,
    client: httpx.AsyncClient,
    *,
    object_type: str,
    filters: list[str] | None = None,
    fields: list[str] | None = None,
    page_size: int = 50,
) -> list[dict[str, Any]]:
    """
    Query Zuora objects via the REST API.

    This mirrors what the MCP query_objects tool does, but called directly
    so we don't need a full agent session.
    """
    params: dict[str, Any] = {"pageSize": page_size}
    if filters:
        params["filter[]"] = filters
    if fields:
        params["fields[]"] = ",".join(fields)

    resp = await _authed_request(
        tenant, client, "GET", f"/v1/object-query/{object_type.lower()}",
        params=params,
    )

    if resp.status_code >= 400:
        # Fall back to older query API
        return await _query_objects_legacy(tenant, client, object_type=object_type, filters=filters, fields=fields, page_size=page_size)

    data = resp.json()
    return data.get("data", data.get("records", []))


async def _query_objects_legacy(
    tenant: Tenant,
    client: httpx.AsyncClient,
    *,
    object_type: str,
    filters: list[str] | None = None,
    fields: list[str] | None = None,
    page_size: int = 50,
) -> list[dict[str, Any]]:
    """Fallback to ZOQL-based query if the object-query endpoint isn't available."""
    field_list = ", ".join(fields) if fields else "*"

    # Map plural names to Zuora object names
    obj_map = {
        "invoices": "Invoice",
        "accounts": "Account",
        "payments": "Payment",
        "paymentmethods": "PaymentMethod",
        "creditmemos": "CreditMemo",
        "billingruns": "BillRun",
    }
    zuora_obj = obj_map.get(object_type.lower(), object_type)

    where_clauses = []
    if filters:
        for f in filters:
            # Parse "field.OP:value" format
            parts = f.split(".", 1)
            if len(parts) == 2:
                field_name = parts[0]
                op_val = parts[1].split(":", 1)
                if len(op_val) == 2:
                    op, val = op_val
                    op_sql = {"EQ": "=", "NE": "!=", "GT": ">", "LT": "<", "GE": ">=", "LE": "<="}
                    sql_op = op_sql.get(op.upper(), "=")
                    # Quote string values
                    try:
                        float(val)
                        where_clauses.append(f"{field_name} {sql_op} {val}")
                    except ValueError:
                        where_clauses.append(f"{field_name} {sql_op} '{val}'")

    zoql = f"SELECT {field_list} FROM {zuora_obj}"
    if where_clauses:
        zoql += " WHERE " + " AND ".join(where_clauses)

    resp = await _authed_request(
        tenant, client, "POST", "/v1/action/query",
        json={"queryString": zoql},
    )

    if resp.status_code >= 400:
        logger.warning("ZOQL query failed: %s — %s", zoql, resp.text[:200])
        return []

    data = resp.json()
    return data.get("records", [])
