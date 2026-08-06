# Hosted-mode build of the Luna image. Build context is the REPO ROOT:
#
#   docker build -f docker/luna-hosted.Dockerfile .
#
# (Plan 019 moved the context from luna/ to the repo root so the build can see
# plugin-set.toml + scripts/bake_plugin_set.py. All luna COPYs are now luna/…)
#
# Two extras over luna/Dockerfile:
#   1. The UI build stage reproduces the repo layout (ui/ and plugins/ as
#      siblings) so ui/src/lib/pluginRegistry.ts's import.meta.glob finds the
#      plugin settings tabs (else "No UI shipped for …").
#   2. A plugin-set stage bakes a curated set of marketplace plugins into
#      /opt/luna/plugin-set (verified by sha256) and the runtime sets
#      LUNA_PLUGIN_SET_DIR so Luna's phase08 loader picks them up at boot — no
#      marketplace network call at tenant runtime.

# ─── Stage 1: Build the UI ───────────────────────────────────────────
FROM node:22-slim AS ui-build
WORKDIR /build/ui
COPY luna/ui/package.json luna/ui/pnpm-lock.yaml luna/ui/pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile --ignore-scripts && pnpm rebuild esbuild
COPY luna/ui/ ./
COPY luna/plugins/ /build/plugins/
RUN pnpm build

# ─── Stage 2: Bake the marketplace plugin set (Plan 019) ─────────────
# Fetches the pinned artifacts, verifies sha256 (fail-closed), unpacks into
# /opt/luna/plugin-set/<pkg>/ + writes plugin-set.lock.json. The set is the UI
# selection (plugin-set.json, written by the build workflow) or the
# plugin-set.toml seed. Needs network during build only.
FROM python:3.12-slim AS plugin-set
WORKDIR /bake
COPY scripts/bake_plugin_set.py ./bake_plugin_set.py
COPY plugin-set.* ./
RUN python bake_plugin_set.py --out /opt/luna/plugin-set --context /bake

# ─── Stage 3: Python runtime ─────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY luna/pyproject.toml luna/README.md ./
COPY luna/luna/ ./luna/
# luna_sdk is the plugin contract package (re-exports luna.*). The luna wheel
# only packages "luna", so without this copy `import luna_sdk` fails and any
# SDK-based marketplace plugin (e.g. plugin-interview) 500s on install/load.
COPY luna/luna_sdk/ ./luna_sdk/
COPY luna/plugins/ ./plugins/
COPY luna/alembic/ ./alembic/
COPY luna/alembic.ini ./
COPY luna/scripts/ ./scripts/
COPY luna/luna_serve.py ./

# Install Python deps
RUN uv pip install --system --no-cache .

# Copy built UI
COPY --from=ui-build /build/ui/dist ./ui/dist

# Image-baked plugin set — read-only, outside any per-tenant writable mount so a
# volume over ~/.luna or /app can't shadow it.
COPY --from=plugin-set /opt/luna/plugin-set /opt/luna/plugin-set
ENV LUNA_PLUGIN_SET_DIR=/opt/luna/plugin-set

# Node 22 runtime for stdio MCP servers (`npx -y <pkg>`) — plugin-mcp's
# contract ("the luna-service image ships Node 22") was never honored here,
# so every npx-based server died with ENOENT. Copied from the ui-build stage
# (same Debian bookworm base as python:3.12-slim); symlinks recreated by hand
# because COPY dereferences them.
COPY --from=ui-build /usr/local/bin/node /usr/local/bin/node
COPY --from=ui-build /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

EXPOSE 8000

CMD ["./scripts/start.sh"]
