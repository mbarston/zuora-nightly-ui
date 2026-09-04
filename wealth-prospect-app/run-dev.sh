#!/usr/bin/env bash
# Dev launcher: FastAPI on :8787 with auto-reload + Vite on :5173.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "==> creating .venv"; python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
if [[ ! -f .venv/.deps-installed ]] || [[ backend/requirements.txt -nt .venv/.deps-installed ]]; then
  echo "==> installing python deps"; pip install --quiet -r backend/requirements.txt; touch .venv/.deps-installed
fi
if [[ ! -d frontend/node_modules ]]; then
  echo "==> installing frontend deps"; (cd frontend && npm install --no-audit --no-fund)
fi
[[ -f .env ]] && set -a && source .env && set +a

(cd frontend && npm run dev) &
VITE_PID=$!
trap 'kill $VITE_PID 2>/dev/null || true' EXIT
echo "==> API  http://127.0.0.1:8787   (docs at /docs)"
echo "==> UI   http://127.0.0.1:5173"
cd backend && exec uvicorn app.main:app --reload --port 8787
