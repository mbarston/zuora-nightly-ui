# Zuora SE Demo Data Agent — User Guide

> Generate realistic demo data in your Zuora sandbox tenants automatically.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Dashboard Overview](#dashboard-overview)
3. [Adding a Tenant](#adding-a-tenant)
4. [Configuring a Tenant](#configuring-a-tenant)
5. [Importing Your Zuora Catalog](#importing-your-zuora-catalog)
6. [Running Demo Data Generation](#running-demo-data-generation)
7. [Stopping a Run](#stopping-a-run)
8. [Scheduling Automated Runs](#scheduling-automated-runs)
9. [Historical Backfills](#historical-backfills)
10. [Chat — Ask Claude About Your Tenant](#chat--ask-claude-about-your-tenant)
11. [Run History](#run-history)
12. [Frequently Asked Questions](#frequently-asked-questions)

---

## Getting Started

### Logging In

When you first visit the app, you'll be taken to the login page.

- **Dev login** — Click the "Dev login" button to sign in as a local test user (`dev@localhost`). This is the default auth method when the app is running with `DEV_AUTH_BYPASS=true`.
- **Google OAuth** — When configured with Google OAuth credentials, click "Sign in with Google" and authorize with your company Google account.

Once logged in, you'll land on the **Dashboard**.

### What This App Does

The Zuora SE Demo Data Agent connects to your Zuora sandbox and creates realistic-looking demo data — new subscriptions, amendments (upgrades, downgrades, add-ons), cancellations, and usage charges. Each "run" executes a Claude-powered skill that reads your tenant configuration and generates data that tells a believable growth story.

---

## Dashboard Overview

The dashboard is your home base. It shows a card for each Zuora sandbox tenant you've registered.

### Tenant Card Anatomy

Each card displays:

- **Tenant name** and **environment** (e.g., "CSBX") with the base URL
- **Health badge** — indicates whether your configuration is ready:
  - **Configured** (green) — no issues, ready to run
  - **N warnings** (amber) — minor config issues, runs still allowed
  - **N errors** (red) — config is incomplete, runs are blocked
- **Last run** — status, timestamp, and cost of the most recent run
- **Next scheduled** — when the next automated run will fire (if a schedule is set)

### Action Buttons

Each tenant card has these action buttons:

| Button | Description |
|--------|-------------|
| **Run now** (play icon) | Start a one-off demo data generation run |
| **Backfill** (calendar icon) | Generate historical data over a date range |
| **Chat** (message icon) | Open an interactive Claude chat connected to this tenant's Zuora data |
| **Configure** (gear icon) | Edit products, volumes, mix percentages, and schedules |
| **Edit** (pencil icon) | Update tenant name, environment, or OAuth credentials |
| **Delete** (trash icon) | Permanently remove the tenant and its stored credentials |

> **Note:** "Run now" and "Backfill" are disabled when the config has errors or a backfill is already in progress.

---

## Adding a Tenant

1. Click the **+ Add tenant** button in the top-right corner of the dashboard.
2. Fill in the form:

| Field | Description | Example |
|-------|-------------|---------|
| **Display name** | A friendly name for this sandbox | `CSBX – Acme Corp Demo` |
| **Environment** | Zuora environment identifier | `CSBX` |
| **Base URL** | Zuora REST API base URL | `https://rest.test.zuora.com` |
| **OAuth client ID** | From Zuora Settings → OAuth Clients | `a5c188d3-...` |
| **OAuth client secret** | The corresponding secret | `A8kNp...` |

3. Click **Create tenant**.

Your credentials are encrypted at rest — the client secret is never stored in plain text.

### Editing a Tenant

Click the **pencil icon** on any tenant card to update its name, environment, base URL, or credentials. When editing, leave the client secret blank to keep the existing one.

---

## Configuring a Tenant

Click the **gear icon** on a tenant card to open the configuration editor. This is where you define what demo data the skill should create.

### Configuration Sections

#### Products

These are the SaaS product tiers that new subscriptions will be created from (e.g., Basic, Professional, Enterprise).

For each product, you define:
- **Label** — Display name (e.g., "CloudStream SaaS Basic")
- **Tier** — Numeric tier level (1 = lowest, used for upgrade/downgrade logic)
- **Rate plans** — One or more billing periods with their Zuora Product Rate Plan IDs:
  - **Name** (e.g., "Monthly" or "Annual")
  - **Period** — MTM (month-to-month), Annual, or Other
  - **Product Rate Plan ID** — The actual Zuora ID (e.g., `8ad09b7e8...`)

#### Add-ons

Standalone rate plans that get attached to existing subscriptions via "add product" amendments (e.g., premium support, API access, additional storage).

Each add-on has a **name** and a **Product Rate Plan ID**.

#### Mandatory Usage Subscriptions

Subscriptions that must receive usage data every run. Typically PPDD (pre-paid drawdown) or minimum-commit subscriptions.

| Field | Description |
|-------|-------------|
| **Subscription number** | e.g., `A-S00000354` |
| **Use case** | e.g., "Minimum Commit" or "Pre-Paid Drawdown" |
| **Notes** | Optional context for the skill |

#### Volume Ranges

How many of each action the skill should create per run. Each has a **min** and **max** — the skill picks a random count in that range.

| Category | What it controls |
|----------|-----------------|
| **New subs** | New subscription orders created |
| **Amendments** | Changes to existing subscriptions (upgrades, downgrades, add/remove products) |
| **Cancellations** | Subscription cancellation orders |
| **Usage posts** | Usage records posted to usage-based subscriptions |

#### Mix Percentages

Controls the distribution of actions within each category.

**Tier mix** — What percentage of new subscriptions land on each product tier. The percentages should sum to approximately 100.

**Amendment mix** — What percentage of amendments are each type:
- **Upgrade** — Move to a higher tier
- **Add product** — Attach an add-on
- **Downgrade** — Move to a lower tier
- **Remove product** — Remove an add-on

#### Growth Bias

A multiplier that controls the growth-vs-churn ratio:
- **100** = neutral (equal growth and churn)
- **150** = 1.5x growth (more new subs than cancellations)
- **50** = 0.5x growth (more churn than growth)

#### Company Name Pool

A list of **prefixes** and **suffixes** used to generate realistic company names for new accounts (e.g., prefix "Apex" + suffix "Technologies" = "Apex Technologies").

Enter comma-separated values in each field.

### Saving

Click the **Save configuration** button in the sticky bar at the bottom-right. The health badge on the dashboard will update to reflect any validation issues.

---

## Importing Your Zuora Catalog

Instead of manually entering Product Rate Plan IDs, you can import directly from your Zuora sandbox.

1. On the configuration page, click **Import from Zuora** (top-right).
2. The modal fetches your live Zuora catalog and displays a two-level checkbox tree:
   - **Products** — expandable, showing their rate plans underneath
   - **Add-ons** — flat list at the bottom
3. Use the **search bar** to filter by name.
4. Use **Select all** / **Select none** for bulk selection.
5. Check the products, rate plans, and add-ons you want.
6. Click **Import selected**.

The imported items merge into your existing configuration — existing items are updated, new ones are added, and anything you didn't select is left untouched.

> **Remember to click Save** after importing — the import only stages changes in the editor.

---

## Running Demo Data Generation

### Starting a Run

1. On the dashboard, click **Run now** (play icon) on the tenant you want.
2. You'll be taken to the **Run Detail** page.
3. Watch events stream in real-time as the skill works through its steps:
   - **Discovery** — queries existing accounts and subscriptions
   - **Planning** — decides what to create based on your configuration
   - **Execution** — creates orders, amendments, usage via the Zuora API
   - **Reporting** — generates a summary of everything created

### Understanding the Event Feed

Events are color-coded:

| Color | Type | Description |
|-------|------|-------------|
| Blue | `tool_use` | Claude is calling a Zuora MCP tool (shows tool name + parameters) |
| Green | `text` | Claude's reasoning or status updates |
| Purple | `result` | Final result with cost and stop reason |
| Red | `error` | Something went wrong |

### Run Completion

When a run finishes:
- **Succeeded** — A green "Report" card appears with a markdown summary of everything created (accounts, subscriptions, amendments, cancellations, usage records).
- **Failed** — A red "Error" card shows the error details and stack trace.
- **Cancelled** — A yellow "Cancelled" card confirms the run was stopped.

---

## Stopping a Run

If a run is taking too long or you need to abort it:

1. Go to the **Run Detail** page (click into the run from the dashboard or history).
2. Click the red **Stop Run** button in the top-right of the run card.
3. The run will be cancelled immediately and marked with status "cancelled".

> **Note:** Any data already created in Zuora during the run will remain — stopping a run does not roll back Zuora API calls that already completed.

---

## Scheduling Automated Runs

You can set up recurring runs on a cron schedule.

### Adding a Schedule

1. Go to the tenant's **Configuration** page (gear icon).
2. Scroll to the **Schedules** section at the bottom.
3. Choose a preset from the dropdown:

| Preset | Description | Example |
|--------|-------------|---------|
| **Every N minutes** | Runs at a fixed interval | Every 30 minutes |
| **Hourly** | Once per hour at a specific minute | At minute :15 |
| **Daily** | Once per day at a specific time | Daily at 09:00 |
| **Weekly** | Specific days of the week | Mon/Wed/Fri at 08:00 |
| **Monthly** | Once per month on a specific day | 1st of each month at 06:00 |
| **Custom** | Enter a raw cron expression | `0 9 * * 1-5` (weekdays at 9am) |

4. The **live preview** shows the next 3 fire times so you can verify it's correct.
5. Optionally add a **label** (e.g., "Nightly").
6. Click **Add schedule**.

### Managing Schedules

- **Enable / Disable** — Toggle a schedule on or off without deleting it.
- **Delete** — Permanently remove a schedule.

### Concurrency Protection

Only one run per tenant can be active at a time. If a scheduled run fires while another run (manual or scheduled) is already in progress, the fire is recorded as "skipped" in history.

---

## Historical Backfills

Backfills let you populate a tenant with months of historical demo data in one go.

### Starting a Backfill

1. On the dashboard, click the **Backfill** button (calendar icon) on the target tenant.
2. In the modal:
   - Set the **start date** (e.g., 12 months ago)
   - Set the **end date** (defaults to today)
   - Optionally add a **label**
3. Review the preview:
   - Number of monthly batches
   - Estimated total cost (based on your average run cost)
   - Batch date chips showing each month that will be generated
4. Click **Start backfill**.

### How Backfills Work

- The system runs **one batch per month**, serially (not in parallel).
- Each batch is a full skill run where all Zuora dates are backdated to that month.
- You can monitor progress on the **Backfill Detail** page:
  - Progress bar showing completed vs. total batches
  - Running cost total
  - Table of child runs (click any to see its events)

### Cancelling a Backfill

Click the **Cancel backfill** button on the backfill detail page. The current batch will finish, then the job stops. Any completed batches are kept.

> **Note:** While a backfill is running, manual runs and scheduled runs for that tenant are blocked.

---

## Chat — Ask Claude About Your Tenant

The chat feature gives you a direct conversational interface with Claude, connected to your tenant's Zuora data via MCP.

### Opening Chat

Click the **Chat** button (message icon) on any tenant card.

### What You Can Ask

Claude has full access to the Zuora MCP tools, so you can:

- **Query data** — "Show me the 5 most recent subscriptions" or "How many active accounts are there?"
- **Inspect records** — "What rate plans does subscription A-S00000354 have?"
- **Create test data** — "Create a new account called Test Corp with a Basic monthly subscription"
- **Analyze patterns** — "What's the breakdown of subscriptions by product tier?"

### Chat Interface

- Type your message and press **Enter** to send (Shift+Enter for a newline).
- Claude's response streams in real-time.
- **Tool use blocks** (blue) show when Claude calls a Zuora API — click to expand and see the parameters.
- **Tool result blocks** show the API response — click to expand the full payload.
- Each message shows its API cost.

### Multi-Turn Conversations

Chat remembers context within a conversation. Ask follow-up questions naturally:

> **You:** Show me all accounts created this month  
> **Claude:** *(queries Zuora, returns list)*  
> **You:** Now show me the subscriptions for the first one  
> **Claude:** *(queries subscriptions for that account)*

Click **New conversation** (refresh icon) to start fresh.

---

## Run History

Click **History** in the top navigation bar (or on the run detail page) to see all runs across all tenants.

The history table shows:

| Column | Description |
|--------|-------------|
| **#** | Run ID |
| **Tenant** | Which tenant this ran against |
| **Trigger** | How it started: manual, schedule, or backfill |
| **Started** | When the run began |
| **Status** | Current status (queued, running, succeeded, failed, cancelled) |
| **Tool calls** | Number of Zuora API calls made |
| **Cost** | Claude API cost for this run |

Click any row to open the full run detail page.

---

## Frequently Asked Questions

### How much does a run cost?

Each run typically costs between $0.50 and $2.00 in Claude API usage, depending on the volume of data generated and the complexity of the tenant configuration. The cost is shown on the run detail page and in the history table.

### Can I run multiple tenants at the same time?

Yes — each tenant has its own concurrency guard, so you can have runs executing on different tenants simultaneously. However, only one run per tenant can be active at a time.

### What happens if a run fails?

The error details are captured and displayed on the run detail page. Any data that was already created in Zuora before the failure will remain. You can simply click "Run now" again to start a new run.

### Can I undo data created by a run?

No — the app creates real data in your Zuora sandbox via the Zuora API. To clean up, you would need to delete the created objects directly in Zuora or reset your sandbox.

### What's the difference between "Run now" and "Backfill"?

- **Run now** creates data dated today — as if your sandbox had one day of normal business activity.
- **Backfill** creates data across a historical date range (one month at a time), so your sandbox looks like it has months or years of realistic transaction history.

### Why is "Run now" disabled?

The button is disabled when:
- Your tenant configuration has **errors** (check the health badge — click Configure to fix issues)
- A **backfill** is currently running for that tenant (wait for it to complete or cancel it)

### How do schedules handle time zones?

Schedules use **server local time**. All timestamps in the UI are displayed in UTC.

### What Zuora environments are supported?

Any Zuora environment that accepts OAuth client credentials and exposes the REST API. Common values:
- **CSBX** (Central Sandbox) — `https://rest.test.zuora.com`
- **Production** — `https://rest.zuora.com` (use with caution!)
- **EU Sandbox** — `https://rest.sandbox.eu.zuora.com`
