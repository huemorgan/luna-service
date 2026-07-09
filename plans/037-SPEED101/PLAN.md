# 037 — SPEED101 (control plane / luna-service)

Companion plan: `luna/plans/025-SPEED101` (tenant runtime + UI). Same project, two codebases.
Basis: `research/speed/001-speed/research.md` (all file:line evidence there).

## Goal

Cut the user-visible latency of the dashboard and every proxied tenant interaction:

| path | today | target |
|---|---|---|
| Dashboard load (settled) | 5–35 s+ | <1 s |
| Proxied tenant API call | 1.5–2.5 s p50 | <500 ms |
| `/api/auth/me` | 1.2 s p50 | <350 ms |
| `/api/admin/luna/branches` | 12 s | <1.5 s |

## Phase 0 — Observability first (so every later phase is measurable)

1. **Timing middleware** (pure ASGI, not `BaseHTTPMiddleware`) in `cloud/main.py`: one structured log line per request — route template, method, status, `duration_ms` — plus `Server-Timing` response header. Log all requests >250 ms, sample ~1% below.
2. **Latency report script** `scripts/latency-report.sh`: pull `render logs -o json`, pair edge `responseTimeMS` with route lines, print p50/p95/max per endpoint (the method from the research). Run before/after each phase.
3. Outbound `httpx` timing via `event_hooks` on the shared clients in `gateway_proxy.py` / `proxy.py` — separates our time from Fly/LLM/GitHub time.

## Phase 1 — Kill the 35-second stalls

4. **Fly-status reconciliation sweep**: periodic task (piggyback on an existing scheduler loop) that lists `luna-agents` machines and marks agents whose machine is gone as `error`. Root cause of the ghost agents.
5. **Fail-fast wake** in `cloud/api/proxy.py`:
   - `_try_wake_agent`: check machine existence first; return False immediately if gone.
   - Always `event.set()` in the `finally` (today failure leaves waiters burning the full 30 s timeout); waiters check a success flag.
   - Lower waiter timeout 30 s → 10 s.
6. **Dashboard identity fix** in `cloud/ui`:
   - `Dashboard.tsx` effect: track *attempted* (ref), not just resolved — stops the retry storm.
   - Better: control plane caches each agent's identity (fetched lazily, TTL or updated on heartbeat) and returns it inside `GET /api/agents` — the per-card `/a/{slug}/…` fan-out disappears. `AgentDetail.tsx` same.

## Phase 2 — Per-request overhead in the hot paths

7. **Gateway proxy session collapse** (`cloud/api/gateway_proxy.py`): one DB session per request instead of 3–4; batch key-mark + usage insert; TTL-cache `get_service` (`gateway/registry.py:89`) like policy/catalog already are.
8. **DB pool tuning** (`cloud/db/session.py`): explicit `pool_size`, `max_overflow`, `pool_pre_ping=True`, `pool_recycle=300`.
9. **Auth caching** (`cloud/auth/deps.py`): short-TTL (30–60 s) in-process cache for session→user/membership lookups.
10. **Uvicorn workers**: `--workers 2` in `cloud/Dockerfile` (RSS ~105 MB fits 2× in 512 MB); isolates long LLM/proxy streams from the UI API. Size pool per worker.
11. **Replace SPA `BaseHTTPMiddleware`** (`cloud/main.py:41-65`) with mounted `StaticFiles` + explicit 404→index fallback route, `Cache-Control: immutable` on hashed assets. Streams stop passing through the middleware bridge.
12. **Parallelize `_list_luna_branches`** (`admin_routes.py:387-408`) with `asyncio.gather` over branches.

## Phase 3 — Hygiene / cost

13. Sync `cloud/render.yaml` plans with reality (declared `standard`, live `starter`) — decide intentionally.
14. Delete `luna-service-cp-upgrade-clone-5d9c` Postgres; suspend or repurpose the idle `luna` (luna-kp8e) Render service.
15. `usage_events` retention/rollup (monthly aggregate + delete raw >90 d).

## Decision: tenant DB stays on Render (for now)

Researched Fly Managed Postgres (July 2026): pgvector ✓, PG16/17 ✓, multi-DB per cluster ✓, PgBouncer ✓, sjc ✓, private network ✓ — **but**: no true superuser (SQL `CREATE DATABASE`/`CREATE ROLE` provisioning as in `cloud/db/tenant_provisioner.py` would have to be rewritten around flyctl), no formal GA, no PITR, managed upgrades "under development", an HA-failure incident thread, and MPG **v2 is mid-rewrite in beta with no v1→v2 migration path**. Migrating now risks a second migration.

**Re-evaluate when MPG v2 is GA with a migration path and SQL-level provisioning.** Until then: architecture stays shared-cluster + database-per-tenant on Render; the latency cost is addressed by pooling on the tenant side (see companion plan) — warm-connection cross-provider queries are ~20–30 ms, acceptable.

## Verification

- `scripts/latency-report.sh` before/after each phase; targets above.
- Dashboard: cold load with ghost agents present settles <1 s, no 35 s requests in logs.
- No regression in gateway proxy streaming (SSE chunks flow, 300 s streams unaffected by worker change).
