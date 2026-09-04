# Multi-stage: build the React app, then serve it from FastAPI.
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=ui /ui/dist frontend/dist
ENV DATABASE_URL=sqlite:////data/prospects.db
VOLUME ["/data"]
EXPOSE 8787
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]
