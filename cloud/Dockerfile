FROM node:22-slim AS ui-build
WORKDIR /build
COPY cloud/ui/package.json cloud/ui/package-lock.json ./
RUN npm ci
COPY cloud/ui/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update && apt-get install -y --no-install-recommends docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv

WORKDIR /app
RUN uv pip install --system --no-cache fastapi "uvicorn[standard]" pydantic pydantic-settings \
    "sqlalchemy[asyncio]" asyncpg alembic authlib itsdangerous httpx python-multipart

COPY cloud/ ./cloud/
COPY --from=ui-build /build/dist ./cloud/ui/dist

EXPOSE 8100
ENV PORT=8100
CMD ["sh", "-c", "uvicorn cloud.main:app --host 0.0.0.0 --port ${PORT}"]
