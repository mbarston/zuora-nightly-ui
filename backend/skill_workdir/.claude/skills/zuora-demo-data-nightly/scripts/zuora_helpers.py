#!/usr/bin/env python3
"""
Zuora Demo Data Helpers — SDK-based operations for actions
the MCP tools don't cover natively.

Covers:
  1. Orders API — AddProduct, UpdateProduct, RemoveProduct, ChangePlan
  2. Usage API — Create individual usage records

Requires: pip install zuora-sdk

Usage:
  python3 zuora_helpers.py add-product    --account <num> --subscription <num> --product-rate-plan-id <id>
  python3 zuora_helpers.py update-product --subscription <num> --rate-plan-id <id> --charge-number <num> --new-quantity <qty>
  python3 zuora_helpers.py remove-product --subscription <num> --rate-plan-id <id>
  python3 zuora_helpers.py change-plan    --subscription <num> --remove-rate-plan-id <id> --add-product-rate-plan-id <id>
  python3 zuora_helpers.py post-usage     --account-id <id> --uom <uom> --quantity <qty> --charge-number <num> --subscription-number <num>
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# SDK client setup
# ---------------------------------------------------------------------------

def _load_creds_from_mcp_config():
    """
    Try to read Zuora credentials from the Claude MCP config file.
    This is where the Zuora MCP server stores its env vars.
    """
    import pathlib
    possible_paths = [
        pathlib.Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        pathlib.Path.home() / ".claude" / "claude_desktop_config.json",
        pathlib.Path.home() / ".config" / "claude" / "claude_desktop_config.json",
    ]

    for config_path in possible_paths:
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = json.load(f)
                # Look through all MCP servers for one with Zuora env vars
                servers = config.get("mcpServers", {})
                for server_name, server_config in servers.items():
                    env = server_config.get("env", {})
                    # Check if this server has Zuora credentials
                    if "ZUORA_CLIENT_ID" in env and "ZUORA_CLIENT_SECRET" in env:
                        return {
                            "client_id": env["ZUORA_CLIENT_ID"],
                            "client_secret": env["ZUORA_CLIENT_SECRET"],
                            "base_url": env.get("ZUORA_BASE_URL", ""),
                            "environment": env.get("ZUORA_ENVIRONMENT", ""),
                        }
            except (json.JSONDecodeError, KeyError):
                continue
    return None


def _guess_environment_from_base_url(base_url):
    """Map a Zuora base URL to a ZuoraEnvironment name."""
    url_map = {
        "rest.apisandbox.zuora.com": "SBX",
        "rest.sandbox.na.zuora.com": "SBX_NA",
        "rest.sandbox.eu.zuora.com": "SBX_EU",
        "rest.test.zuora.com": "CSBX",
        "rest.test.eu.zuora.com": "CSBX_EU",
        "rest.test.ap.zuora.com": "CSBX_AP",
        "rest.zuora.com": "PROD",
        "rest.na.zuora.com": "PROD_NA",
        "rest.eu.zuora.com": "PROD_EU",
        "rest.ap.zuora.com": "PROD_AP",
    }
    for domain, env in url_map.items():
        if domain in base_url:
            return env
    return None


def get_client(override_client_id=None, override_client_secret=None, override_env=None):
    """
    Initialize and return a Zuora SDK client.

    Credential resolution order:
      1. Explicit overrides (CLI args)
      2. Environment variables (ZUORA_CLIENT_ID, ZUORA_CLIENT_SECRET, ZUORA_ENVIRONMENT)
      3. Claude MCP config file (where the Zuora MCP server stores its creds)
    """
    try:
        from zuora_sdk.zuora_client import ZuoraClient, ZuoraEnvironment
    except ImportError:
        print("ERROR: zuora-sdk not installed. Run: pip install zuora-sdk --break-system-packages")
        sys.exit(1)

    # --- Resolve credentials ---
    client_id = override_client_id or os.environ.get("ZUORA_CLIENT_ID")
    client_secret = override_client_secret or os.environ.get("ZUORA_CLIENT_SECRET")
    env_name = override_env or os.environ.get("ZUORA_ENVIRONMENT", "")

    # If still missing, try the MCP config
    if not client_id or not client_secret:
        mcp_creds = _load_creds_from_mcp_config()
        if mcp_creds:
            client_id = client_id or mcp_creds["client_id"]
            client_secret = client_secret or mcp_creds["client_secret"]
            if not env_name:
                # Try to derive environment from base_url in MCP config
                if mcp_creds["environment"]:
                    env_name = mcp_creds["environment"]
                elif mcp_creds["base_url"]:
                    env_name = _guess_environment_from_base_url(mcp_creds["base_url"]) or "SBX"
            print(f"INFO: Using credentials from Claude MCP config")
        else:
            print("ERROR: No Zuora credentials found. Checked:")
            print("  1. CLI arguments (--client-id, --client-secret)")
            print("  2. Environment variables (ZUORA_CLIENT_ID, ZUORA_CLIENT_SECRET)")
            print("  3. Claude MCP config file (claude_desktop_config.json)")
            sys.exit(1)

    env_name = env_name.upper() if env_name else "SBX"

    env_map = {
        "SBX": ZuoraEnvironment.SBX,
        "SBX_NA": ZuoraEnvironment.SBX_NA,
        "SBX_EU": ZuoraEnvironment.SBX_EU,
        "CSBX": ZuoraEnvironment.CSBX,
        "CSBX_EU": ZuoraEnvironment.CSBX_EU,
        "PROD": ZuoraEnvironment.PROD,
        "PROD_NA": ZuoraEnvironment.PROD_NA,
        "PROD_EU": ZuoraEnvironment.PROD_EU,
    }

    env = env_map.get(env_name)
    if not env:
        print(f"ERROR: Unknown ZUORA_ENVIRONMENT '{env_name}'. Valid: {', '.join(env_map.keys())}")
        sys.exit(1)

    client = ZuoraClient(
        client_id=client_id,
        client_secret=client_secret,
        env=env
    )
    client.initialize()
    return client


# ---------------------------------------------------------------------------
# Orders API — Create Order with various action types
# ---------------------------------------------------------------------------

def create_order(client, account_number, subscription_number, order_actions, description=""):
    """
    Create an order against an existing subscription.

    Args:
        client: Initialized ZuoraClient
        account_number: The account number (e.g., "A00000001")
        subscription_number: The subscription number to amend
        order_actions: List of order action dicts
        description: Optional order description
    """
    from zuora_sdk.models.create_order_request import CreateOrderRequest

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    request = CreateOrderRequest(
        existing_account_number=account_number,
        order_date=today,
        description=description or f"Demo data order - {today}",
        subscriptions=[{
            "subscription_number": subscription_number,
            "order_actions": order_actions
        }]
    )

    try:
        response = client.orders_api().create_order(request)
        result = {
            "success": getattr(response, 'success', True),
            "order_number": getattr(response, 'order_number', None),
            "subscription_numbers": getattr(response, 'subscription_numbers', []),
        }
        print(json.dumps(result, indent=2, default=str))
        return result
    except Exception as e:
        error = {"success": False, "error": str(e)}
        print(json.dumps(error, indent=2))
        return error


def add_product(client, account_number, subscription_number, product_rate_plan_id):
    """Add a product (rate plan) to an existing subscription."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    order_actions = [{
        "type": "AddProduct",
        "trigger_dates": [
            {"name": "ContractEffective", "trigger_date": today},
            {"name": "ServiceActivation", "trigger_date": today},
            {"name": "CustomerAcceptance", "trigger_date": today}
        ],
        "add_product": {
            "product_rate_plan_id": product_rate_plan_id
        }
    }]

    return create_order(
        client, account_number, subscription_number, order_actions,
        description=f"Demo: Add product {product_rate_plan_id}"
    )


def update_product(client, account_number, subscription_number, rate_plan_id,
                   charge_number=None, new_quantity=None):
    """
    Update a product on an existing subscription.
    Can update charge quantity (useful for per-unit upgrades/downgrades).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    charge_updates = []
    if charge_number and new_quantity is not None:
        charge_updates.append({
            "charge_number": charge_number,
            "pricing": {
                "recurring_per_unit": {
                    "quantity": new_quantity
                }
            }
        })

    order_actions = [{
        "type": "UpdateProduct",
        "trigger_dates": [
            {"name": "ContractEffective", "trigger_date": today},
            {"name": "ServiceActivation", "trigger_date": today},
            {"name": "CustomerAcceptance", "trigger_date": today}
        ],
        "update_product": {
            "rate_plan_id": rate_plan_id,
            "charge_updates": charge_updates if charge_updates else []
        }
    }]

    return create_order(
        client, account_number, subscription_number, order_actions,
        description=f"Demo: Update product on rate plan {rate_plan_id}"
    )


def remove_product(client, account_number, subscription_number, rate_plan_id):
    """Remove a product (rate plan) from an existing subscription."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    order_actions = [{
        "type": "RemoveProduct",
        "trigger_dates": [
            {"name": "ContractEffective", "trigger_date": today},
            {"name": "ServiceActivation", "trigger_date": today},
            {"name": "CustomerAcceptance", "trigger_date": today}
        ],
        "remove_product": {
            "rate_plan_id": rate_plan_id
        }
    }]

    return create_order(
        client, account_number, subscription_number, order_actions,
        description=f"Demo: Remove rate plan {rate_plan_id}"
    )


def change_plan(client, account_number, subscription_number,
                remove_rate_plan_id, add_product_rate_plan_id):
    """
    Swap one rate plan for another (upgrade/downgrade).
    Removes the old rate plan and adds the new one in one order.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    order_actions = [
        {
            "type": "RemoveProduct",
            "trigger_dates": [
                {"name": "ContractEffective", "trigger_date": today},
                {"name": "ServiceActivation", "trigger_date": today},
                {"name": "CustomerAcceptance", "trigger_date": today}
            ],
            "remove_product": {
                "rate_plan_id": remove_rate_plan_id
            }
        },
        {
            "type": "AddProduct",
            "trigger_dates": [
                {"name": "ContractEffective", "trigger_date": today},
                {"name": "ServiceActivation", "trigger_date": today},
                {"name": "CustomerAcceptance", "trigger_date": today}
            ],
            "add_product": {
                "product_rate_plan_id": add_product_rate_plan_id
            }
        }
    ]

    return create_order(
        client, account_number, subscription_number, order_actions,
        description=f"Demo: Change plan - swap {remove_rate_plan_id} -> {add_product_rate_plan_id}"
    )


# ---------------------------------------------------------------------------
# Usage API — Post usage records
# ---------------------------------------------------------------------------

def post_usage(client, account_id=None, account_number=None,
               subscription_number=None, charge_number=None,
               uom="Units", quantity=1000, start_date=None):
    """
    Create a usage record for a usage-based charge.

    Args:
        client: Initialized ZuoraClient
        account_id: Zuora account ID (use this or account_number)
        account_number: Zuora account number (use this or account_id)
        subscription_number: Subscription number containing the charge
        charge_number: The charge number for the usage-based charge
        uom: Unit of measure (must match the charge definition)
        quantity: Usage quantity
        start_date: Start datetime (ISO format). Defaults to now.
    """
    from zuora_sdk.models.create_usage_request import CreateUsageRequest

    if not start_date:
        start_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+00:00")

    request_params = {
        "uom": uom,
        "quantity": float(quantity),
        "start_date_time": start_date,
        "description": f"Auto-generated demo usage - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    }

    if account_id:
        request_params["account_id"] = account_id
    elif account_number:
        request_params["account_number"] = account_number

    if subscription_number:
        request_params["subscription_number"] = subscription_number
    if charge_number:
        request_params["charge_number"] = charge_number

    request = CreateUsageRequest(**request_params)

    try:
        response = client.usage_api().create_usage(request)
        result = {
            "success": getattr(response, 'success', True),
            "id": getattr(response, 'id', None),
        }
        print(json.dumps(result, indent=2, default=str))
        return result
    except Exception as e:
        error = {"success": False, "error": str(e)}
        print(json.dumps(error, indent=2))
        return error


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Zuora Demo Data Helpers — SDK operations for amendments and usage"
    )

    # Global auth flags (optional — falls back to MCP config automatically)
    parser.add_argument("--client-id", help="Zuora OAuth client ID (optional, auto-detected from MCP config)")
    parser.add_argument("--client-secret", help="Zuora OAuth client secret (optional, auto-detected from MCP config)")
    parser.add_argument("--environment", help="Zuora environment: SBX, SBX_NA, CSBX, PROD, etc. (optional, auto-detected)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- add-product ---
    p_add = subparsers.add_parser("add-product", help="Add a product to a subscription")
    p_add.add_argument("--account", required=True, help="Account number")
    p_add.add_argument("--subscription", required=True, help="Subscription number")
    p_add.add_argument("--product-rate-plan-id", required=True, help="Product rate plan ID to add")

    # --- update-product ---
    p_upd = subparsers.add_parser("update-product", help="Update a product on a subscription")
    p_upd.add_argument("--account", required=True, help="Account number")
    p_upd.add_argument("--subscription", required=True, help="Subscription number")
    p_upd.add_argument("--rate-plan-id", required=True, help="Subscription rate plan ID")
    p_upd.add_argument("--charge-number", help="Charge number to update")
    p_upd.add_argument("--new-quantity", type=float, help="New quantity for the charge")

    # --- remove-product ---
    p_rem = subparsers.add_parser("remove-product", help="Remove a product from a subscription")
    p_rem.add_argument("--account", required=True, help="Account number")
    p_rem.add_argument("--subscription", required=True, help="Subscription number")
    p_rem.add_argument("--rate-plan-id", required=True, help="Subscription rate plan ID to remove")

    # --- change-plan ---
    p_chg = subparsers.add_parser("change-plan", help="Swap one rate plan for another")
    p_chg.add_argument("--account", required=True, help="Account number")
    p_chg.add_argument("--subscription", required=True, help="Subscription number")
    p_chg.add_argument("--remove-rate-plan-id", required=True, help="Rate plan ID to remove")
    p_chg.add_argument("--add-product-rate-plan-id", required=True, help="Product rate plan ID to add")

    # --- post-usage ---
    p_usg = subparsers.add_parser("post-usage", help="Post a usage record")
    p_usg.add_argument("--account-id", help="Account ID")
    p_usg.add_argument("--account-number", help="Account number")
    p_usg.add_argument("--subscription-number", help="Subscription number")
    p_usg.add_argument("--charge-number", help="Charge number for usage charge")
    p_usg.add_argument("--uom", default="Units", help="Unit of measure")
    p_usg.add_argument("--quantity", type=float, required=True, help="Usage quantity")
    p_usg.add_argument("--start-date", help="Start date (ISO format)")

    args = parser.parse_args()
    client = get_client(
        override_client_id=args.client_id,
        override_client_secret=args.client_secret,
        override_env=args.environment
    )

    if args.command == "add-product":
        add_product(client, args.account, args.subscription, args.product_rate_plan_id)

    elif args.command == "update-product":
        update_product(client, args.account, args.subscription, args.rate_plan_id,
                      args.charge_number, args.new_quantity)

    elif args.command == "remove-product":
        remove_product(client, args.account, args.subscription, args.rate_plan_id)

    elif args.command == "change-plan":
        change_plan(client, args.account, args.subscription,
                   args.remove_rate_plan_id, args.add_product_rate_plan_id)

    elif args.command == "post-usage":
        post_usage(client,
                  account_id=args.account_id,
                  account_number=args.account_number,
                  subscription_number=args.subscription_number,
                  charge_number=args.charge_number,
                  uom=args.uom,
                  quantity=args.quantity,
                  start_date=args.start_date)


if __name__ == "__main__":
    main()
