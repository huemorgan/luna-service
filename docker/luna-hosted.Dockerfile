# Hosted-mode build of the Luna image. Build context is the luna/ submodule:
#
#   docker build -f docker/luna-hosted.Dockerfile luna/
#
# Mirrors luna/Dockerfile with one fix: the UI build stage reproduces the
# repo layout (ui/ and plugins/ as siblings) so that
#   - ui/src/lib/pluginRegistry.ts's import.meta.glob('../../../plugins/*/
#     interface/webui/SettingsTab.tsx') finds the plugin settings tabs, and
#   - those tabs' imports back into '../../../../ui/src/lib/...' resolve.
# The stock Dockerfile builds the UI without plugins/ present, so every
# plugin settings tab is missing from the built UI ("No UI shipped for ...").

# ─── Stage 1: Build the UI ───────────────────────────────────────────
FROM node:22-slim AS ui-build
WORKDIR /build/ui
COPY ui/package.json ui/pnpm-lock.yaml ui/pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile --ignore-scripts && pnpm rebuild esbuild
COPY ui/ ./
COPY plugins/ /build/plugins/
RUN pnpm build

# ─── Stage 2: Python runtime ────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml README.md ./
COPY luna/ ./luna/
COPY plugins/ ./plugins/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY scripts/ ./scripts/
COPY luna_serve.py ./

# Install Python deps
RUN uv pip install --system --no-cache .

# Copy built UI
COPY --from=ui-build /build/ui/dist ./ui/dist

EXPOSE 8000

CMD ["./scripts/start.sh"]
