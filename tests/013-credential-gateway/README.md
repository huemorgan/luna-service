# 013 — Credential Gateway test suite

Verifies the credential gateway: dynamic service registry, two-level key pool
(global with priority fallback + per-agent overrides), universal proxy with
`lsv1-` tenant tokens, BYOK passthrough, and registry-driven provisioning.

## Setup

- Control plane running locally (`uvicorn cloud.main:app --port 8100`) with
  the local Postgres from `docker-compose.local.yml`
- Stub upstream running (`python dev/stub_upstream.py`, port 9009) — echoes
  back the auth headers it received, so we can prove key injection /
  passthrough without spending real API money
- Admin session (vaselin@gmail.com via stub identity provider)

## Scenarios

| # | File | Proves |
|---|------|--------|
| 01 | 01-admin-services-page.md | Registry UI: seeded services visible, dynamic add |
| 02 | 02-key-pool-write-only.md | Key pool UI: add global keys, values never shown back |
| 03 | 03-proxy-managed-flow.md | Tenant token → real key injected, usage metered billable |
| 04 | 04-key-fallback.md | Priority-1 key failing → priority-2 takes over, cooldown visible |
| 05 | 05-byok-passthrough.md | Non-lsv1 credential → passthrough, no substitution, not billed |
| 06 | 06-agent-override-key.md | Agent-scoped key beats global for that agent only |
| 07 | 07-provisioning-env.md | Provisioned machine env: proxy URLs + token, no real keys |
