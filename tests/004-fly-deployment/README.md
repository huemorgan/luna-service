# Phase 004 — Test Scenarios

Production deployment validation. Many scenarios are repeats of phase 003 — now run against `https://luna.com.ai`.

## Setup

Once production stack is deployed:
- `https://luna.com.ai` resolves (Cloudflare DNS)
- Control plane lives on Render
- Tenant DB on Render Postgres (second instance, schema-per-tenant, pgvector + HNSW)
- Luna fleet on Fly

Use real Google accounts (test accounts in Novalystrix Workspace). No stub identity in production.

## Scenarios

| # | Scenario | File |
|---|----------|------|
| 01 | DNS + TLS correctness | `01-dns-tls.md` |
| 02 | Phase 003 scenarios re-run on prod | `02-phase003-on-prod.md` |
| 03 | Fly Machine lifecycle | `03-fly-machine-lifecycle.md` |
| 04 | Render → Fly internal connectivity | `04-render-to-fly.md` |
| 05 | Control plane restart resilience | `05-control-plane-restart.md` |
| 06 | Cold mobile first-impression test | `06-mobile-first-impression.md` |
| 07 | Multi-user production isolation | `07-prod-multi-user.md` |
| 08 | Production MVP walkthrough | `08-prod-mvp-walkthrough.md` |
