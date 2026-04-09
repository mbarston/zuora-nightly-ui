# zuora-nightly-ui

Internal web app for running the Zuora `zuora-demo-data-nightly` skill per
user, per tenant. Self-hosted, Google SSO-gated, with encrypted credential
storage and both on-demand + scheduled runs.

## Phase status

| Phase | What works |
|---|---|
| **1** (current) | Scaffolding, Google SSO with domain gate, tenant CRUD, Fernet-encrypted credentials, dashboard listing |
| **2** (next) | On-demand runs via Claude Agent SDK, live run detail page with streaming tool calls, reports |
| **3** | APScheduler for per-tenant schedules, team-visible read-only history |
| **4** | Admin view, report diffs, optional Slack/email notifications |

## Stack

- **FastAPI** (Python 3.11+) — single `uvicorn` process
- **SQLite** via SQLAlchemy — one file at `data/app.db`, swap to Postgres later
- **Jinja2 + HTMX + Pico.css** — server-rendered, no frontend build
- **Authlib** — Google OAuth 2.0 with domain gating
- **Fernet (cryptography.io)** — envelope encryption for Zuora client secrets
- **Claude Agent SDK** — Phase 2

## Quick start (local dev)

### 1. Prereqs
- Python 3.11+
- (Phase 2) `pip install zuora-sdk` so the existing `zuora_helpers.py` works

### 2. Configure
```bash
cd ~/Documents/Code/zuora-nightly-ui
cp .env.example .env
```

Generate the two required secrets and paste them into `.env`:
```bash
python3 -c "import secrets; print('SESSION_SECRET=' + secrets.token_urlsafe(48))"
python3 -c "from cryptography.fernet import Fernet; print('MASTER_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
```
(You'll need to install `cryptography` first or run these after `./run-dev.sh` has created the venv.)

Leave `DEV_AUTH_BYPASS=true` for now so you don't need Google OAuth configured
to try it out. You'll see a "Dev login (bypass)" button on the login page.

### 3. Run
```bash
./run-dev.sh
```

First run will create `.venv/`, install deps, and start `uvicorn` with
auto-reload. Open http://localhost:8000.

## Setting up Google OAuth (for real SSO)

1. Go to https://console.cloud.google.com/apis/credentials → **Create
   Credentials** → **OAuth client ID** → **Web application**
2. Name: "zuora-nightly-ui (local)"
3. Authorized redirect URI: `http://localhost:8000/auth/callback`
4. Click Create, copy the **Client ID** and **Client secret**
5. Paste both into `.env`:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   ```
6. Set `DEV_AUTH_BYPASS=false`
7. Restart `./run-dev.sh`

Domain gating (`ALLOWED_EMAIL_DOMAIN=zuora.com` by default) runs server-side
after Google completes the OAuth handshake — anyone outside the allowed
domain gets a 403 and no user row is created.

## Project layout

```
zuora-nightly-ui/
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app factory
│   │   ├── config.py         # pydantic-settings, loads .env
│   │   ├── db.py             # SQLAlchemy engine + session + init
│   │   ├── models.py         # User, Tenant (Phase 2 adds Run, RunEvent)
│   │   ├── crypto.py         # Fernet encrypt/decrypt for client secrets
│   │   ├── auth.py           # Google OAuth + dev-login routes
│   │   ├── deps.py           # current_user / require_login_redirect
│   │   ├── templates.py      # shared Jinja2Templates
│   │   └── routers/
│   │       ├── pages.py      # login + dashboard
│   │       └── tenants.py    # tenant CRUD (HTML + HTMX)
│   ├── templates/            # Jinja2 HTML
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── dashboard.html
│   │   └── tenants/form.html
│   └── static/               # (empty for now; pico.css + htmx come from CDN)
├── data/                     # SQLite DB lives here (gitignored)
├── .env.example
├── .env                      # (gitignored)
├── pyproject.toml
├── run-dev.sh
└── README.md
```

## Security notes (read before exposing this to anyone)

- **Session cookie**: signed with `SESSION_SECRET`. Rotating the secret logs
  everyone out. In prod, terminate TLS in front and flip `same_site=strict`
  + `https_only=True` in `main.py`.
- **Credential encryption**: Zuora `client_secret` values are encrypted at
  rest with a single Fernet master key (`MASTER_ENCRYPTION_KEY`). The key
  lives in `.env` on the server's filesystem. If the DB is stolen without
  the key, secrets are safe. If the server is fully compromised, they aren't.
  For stronger separation, back the key with the macOS Keychain or an
  external secrets manager (Phase 3 hardening).
- **Dev bypass**: `DEV_AUTH_BYPASS=true` lets anyone who can reach the server
  POST `/auth/dev-login` and become a user. The app logs a loud warning at
  startup. Turn it off before deploying.
- **Domain gating**: Server-side check after Google returns a userinfo
  payload. Not a replacement for Google Workspace "internal app" configuration
  (which is stricter), but sufficient for an internal tool on a trusted box.

## What's NOT in Phase 1 (intentionally)

- Running the skill — "Run now" is a disabled button
- Schedules
- Team-visible history
- Report rendering
- Admin view
- Audit logging
- Alembic migrations (using `create_all()` while the schema churns)

Those all land in Phases 2–4.
