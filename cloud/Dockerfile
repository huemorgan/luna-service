FROM node:22-slim AS ui-build
WORKDIR /build
COPY cloud/ui/package.json cloud/ui/package-lock.json ./
RUN npm ci
COPY cloud/ui/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv

WORKDIR /app
RUN uv pip install --system --no-cache fastapi "uvicorn[standard]" pydantic pydantic-settings \
    "sqlalchemy[asyncio]" asyncpg alembic authlib itsdangerous httpx python-multipart

COPY cloud/ ./cloud/
COPY --from=ui-build /build/dist ./cloud/ui/dist

EXPOSE 8100
ENV PORT=8100
# 2 workers (plan 037-SPEED101): isolates long LLM/proxy streams from the UI
# API; RSS ~105 MB fits 2x in the 512 MB instance. Background loops are
# advisory-lock guarded so they still run once (cloud/runtime/exclusive.py).
# Migrations run first (plan 039/001) and abort the deploy on failure — the
# old app keeps serving because Render only swaps after a healthy start.
CMD ["sh", "-c", "python -m cloud.db.migrate && uvicorn cloud.main:app --host 0.0.0.0 --port ${PORT} --workers 2"]
