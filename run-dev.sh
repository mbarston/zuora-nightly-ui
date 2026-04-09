#!/usr/bin/env bash
#
# Dev launcher. Creates a local venv on first run, installs deps,
# and starts uvicorn with auto-reload.
#
set -euo pipefail
cd "$(dirname "$0")"

# --- venv --------------------------------------------------------------------
if [[ ! -d .venv ]]; then
  echo "==> creating .venv"
  python3 -m venv .venv
fi

# On macOS + APFS, dotfile directories (like .venv) get UF_HIDDEN set and
# that flag is inherited by every file created inside. Python 3.13's site.py
# silently skips .pth files with UF_HIDDEN, which breaks module discovery.
# Clear the whole tree every startup — it's cheap and idempotent.
if [[ "$(uname)" == "Darwin" ]]; then
  chflags -R nohidden .venv 2>/dev/null || true
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# --- deps --------------------------------------------------------------------
if [[ ! -f .venv/.deps-installed ]] || [[ pyproject.toml -nt .venv/.deps-installed ]]; then
  echo "==> installing deps"
  pip install --quiet --upgrade pip
  pip install --quiet -e .
  touch .venv/.deps-installed
fi

# --- sys.path wiring ---------------------------------------------------------
# We put `backend/` on sys.path via a plain .pth file instead of setuptools'
# editable install. Rationale: on macOS + Python 3.13, setuptools' generated
# __editable__*.pth files get the UF_HIDDEN filesystem flag set for reasons
# I still don't fully understand, and Python 3.13's site.py silently ignores
# hidden .pth files. A hand-written .pth sidesteps the issue entirely.
SITE_PACKAGES=$(.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
PTH_FILE="${SITE_PACKAGES}/zuora_nightly_ui.pth"
BACKEND_PATH="$(pwd)/backend"
if [[ ! -f "$PTH_FILE" ]] || ! grep -qxF "$BACKEND_PATH" "$PTH_FILE" 2>/dev/null; then
  printf '%s\n' "$BACKEND_PATH" > "$PTH_FILE"
fi

# --- env ---------------------------------------------------------------------
if [[ ! -f .env ]]; then
  echo
  echo "ERROR: .env not found. Copy .env.example to .env and fill in the"
  echo "       REQUIRED values (SESSION_SECRET, MASTER_ENCRYPTION_KEY)."
  echo
  exit 1
fi

# --- frontend deps -----------------------------------------------------------
if [[ -d frontend ]]; then
  if [[ ! -d frontend/node_modules ]] || [[ frontend/package.json -nt frontend/node_modules/.package-lock.json ]]; then
    echo "==> installing frontend deps"
    (cd frontend && npm install)
  fi
fi

# --- run ---------------------------------------------------------------------
# Two processes: FastAPI on :8765 serving the JSON API, Vite on :5173 serving
# the React app and proxying /api /auth /runs to the backend. When you Ctrl-C,
# both die via the trap.
BACKEND_HOST="${APP_HOST:-127.0.0.1}"
BACKEND_PORT="${APP_PORT:-8765}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

echo "==> backend: http://${BACKEND_HOST}:${BACKEND_PORT}"
echo "==> frontend (open this): http://${BACKEND_HOST}:${FRONTEND_PORT}"
echo

pids=()
cleanup() {
  for pid in "${pids[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

uvicorn app.main:app \
  --app-dir backend \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT" \
  --reload \
  --reload-dir backend &
pids+=($!)

if [[ -d frontend ]]; then
  (cd frontend && npm run dev -- --host "$BACKEND_HOST" --port "$FRONTEND_PORT") &
  pids+=($!)
fi

wait
