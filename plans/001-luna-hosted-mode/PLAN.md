# Phase 001 — Luna Hosted Mode

## Purpose

Modify Luna (OSS) to support running in **trusted-proxy mode**: identity is asserted by an upstream proxy via the `X-Luna-User` header rather than via Luna's own login screen. Build a hosted Docker image and verify it works locally with a fake proxy.

This is the **only phase that modifies Luna OSS code**. The change is small, generally useful (any reverse-proxy SSO benefits from it), and tracked upstream as plan `005.903` in Luna's own roadmap.

## Result

After this phase:

- Luna can be configured to skip its own login UI and trust an `X-Luna-User` header
- Header is accepted only when a shared `LUNA_TRUSTED_PROXY_SECRET` matches
- Header is accepted only when Luna is bound to a non-public address (`127.0.0.1` or internal Docker network)
- A hosted-mode Docker image is built and tagged
- Manual test: `docker run` Luna with trust-proxy mode → curl with header → get user-scoped responses

## Prerequisites

- Luna submodule pulled (already at `luna/`)
- Docker installed locally
- Anthropic API key (already in `luna-dojo/luna/.env`)

## Tasks

### 1. Luna OSS changes (in the `luna/` submodule)

Branch in the submodule: `005.903-trusted-proxy-mode`

- [ ] Add config flags to `luna/luna/config/schema.py`:
  - `LUNA_AUTH_MODE`: `"local"` (default, current behavior) | `"trusted_proxy"`
  - `LUNA_TRUSTED_PROXY_SECRET`: required when mode is `trusted_proxy`
  - `LUNA_TRUSTED_PROXY_HEADER_USER`: default `"X-Luna-User"`
  - `LUNA_TRUSTED_PROXY_HEADER_ACCOUNT`: default `"X-Luna-Account"` (optional, for future)
  - `LUNA_BIND_HOST`: validate it's `127.0.0.1` or `0.0.0.0` only inside Docker bridge when trust mode is on
- [ ] In `plugins/plugin_web/security.py` (or wherever auth lives), add `TrustedProxyAuthBackend`:
  - Reads `X-Luna-User` from request
  - Verifies `X-Luna-Proxy-Secret` header matches `LUNA_TRUSTED_PROXY_SECRET`
  - Rejects request (401) if header missing or secret mismatch
  - Sets request user to the value from `X-Luna-User`
- [ ] In `plugins/plugin_web/__init__.py` (or the FastAPI app factory):
  - When `LUNA_AUTH_MODE=trusted_proxy`, mount `TrustedProxyAuthBackend` and **disable** the login/signup routes
  - When `LUNA_AUTH_MODE=local`, current behavior (unchanged)
- [ ] In UI (`luna/ui/src/`): if backend reports auth mode is `trusted_proxy`, hide login/signup screens — just go to chat
  - Add `/api/auth/mode` endpoint that returns `{"mode": "local" | "trusted_proxy"}`
  - UI's auth check uses this to skip login flow when in trusted mode

### 2. Database multi-tenancy support (search_path)

- [ ] Add `LUNA_DB_SCHEMA` env var (default: `public`, current behavior)
- [ ] On startup, when `LUNA_DB_SCHEMA` is set and not `public`:
  - Set the SQLAlchemy engine's connection-level `search_path` to the schema name
  - Verify schema exists (fail clear if not — control plane creates it before starting Luna)
- [ ] **Do not** add tenant_id columns or alter any tables; the search_path approach keeps Luna's models unchanged

### 3. Configurable vault key source (minimal)

- [ ] Vault key can already be set via `LUNA_VAULT_MASTER_KEY` env var. No code change needed for MVP — control plane passes a unique key per Luna instance (we'll add proper KMS derivation post-MVP).

### 4. Build hosted Docker image

- [ ] Verify Luna's existing `Dockerfile` works with the new env vars
- [ ] Create `docker/hosted.Dockerfile` (or extend existing) that:
  - Builds the UI (`pnpm build`)
  - Installs Python deps
  - Sets `LUNA_AUTH_MODE=trusted_proxy` as default
  - Sets `LUNA_BIND_HOST=0.0.0.0` (Docker network — exposed only to control plane)
  - CMD runs `scripts/start.sh` (already exists, runs migrations + uvicorn)
- [ ] Tag image as `luna-hosted:dev-001`

### 5. Local test harness (no control plane yet)

In this repo (`luna-service/`), create `dev/local-luna/`:

- [ ] `docker-compose.yml` that starts:
  - Postgres (with a test schema pre-created)
  - Redis
  - Luna in hosted mode with test env vars
  - `nginx` as a fake control-plane proxy that injects `X-Luna-User: test-user` and `X-Luna-Proxy-Secret: dev-secret`
- [ ] `Makefile`:
  - `make up` — start the stack
  - `make test-trust-mode` — curl through nginx, verify Luna responds
  - `make test-direct-rejection` — curl Luna directly (bypassing nginx) → 401
  - `make logs`, `make down`

### 6. Contribute upstream

- [ ] Open PR against `huemorgan/luna` with the Phase 005.903 changes
- [ ] Once merged, bump the submodule pin in this repo

## Tests

Write **before** implementation in `tests/001-luna-hosted-mode/`. See that folder for the scenarios.

## Definition of Done

- [ ] All Luna unit tests pass with both `LUNA_AUTH_MODE=local` and `LUNA_AUTH_MODE=trusted_proxy`
- [ ] Local docker-compose stack starts cleanly
- [ ] All dojo scenarios in `tests/001-luna-hosted-mode/` pass
- [ ] Live walkthrough: open chat through the fake proxy, have a 3-turn conversation, observe correct behavior
- [ ] Docker image `luna-hosted:dev-001` built and reproducible
- [ ] Luna OSS PR opened (merge can happen in parallel with phase 002 work)
- [ ] Documented in `dojo-results/0001-001-luna-hosted-mode/summary.md`
