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
# gosu lets the entrypoint fix volume ownership as root then drop privileges.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates gosu \
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

# Create non-root user (Claude CLI refuses --permission-mode bypassPermissions as root)
RUN useradd -m -s /bin/bash agent && chown -R agent:agent /app /data

# Entrypoint fixes /data volume ownership then drops to 'agent' via gosu
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Put backend/ on PYTHONPATH so `import app` works without editable install
ENV PYTHONPATH=/app/backend
# Point SQLite at the persistent volume
ENV DATABASE_URL=sqlite:////data/app.db

EXPOSE 8765

# Start as root so entrypoint can chown the volume, then gosu drops to agent
CMD ["/entrypoint.sh"]
