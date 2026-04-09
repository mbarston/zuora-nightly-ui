# Zuora SE Demo Data Agent — single-container deploy
#
# Builds the React frontend, installs Python deps, and runs uvicorn
# serving both the JSON API (/api/*) and the built SPA (/*) from one
# process.
#
# Build:  docker build -t zuora-se-agent .
# Run:    docker run -p 8765:8765 --env-file .env zuora-se-agent

FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime
WORKDIR /app

# System deps for the claude-agent-sdk bundled CLI + npx (zuora-mcp)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . 2>/dev/null || pip install --no-cache-dir .

# Backend source
COPY backend/ ./backend/

# Frontend build output (served by FastAPI's SPA fallback)
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Data directory for SQLite (mount a persistent volume here on Fly)
RUN mkdir -p /data

# Put backend/ on PYTHONPATH so `import app` works without editable install
ENV PYTHONPATH=/app/backend
# Point SQLite at the persistent volume
ENV DATABASE_URL=sqlite:////data/app.db

EXPOSE 8765

CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8765", \
     "--workers", "1", "--log-level", "info"]
