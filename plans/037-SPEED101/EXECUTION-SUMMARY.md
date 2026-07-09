# 037 — SPEED101 Execution Summary (control plane / luna-service)

Executed 2026-07-09. Companion summary: `luna/plans/027-SPEED101/EXECUTION-SUMMARY.md`.
Commits: `18c6124` (implementation), `aff5e73` (submodule bump to luna 0.33.005). Deployed to
`luna-service.onrender.com` via Render API (`dep-d97s922m53os73c02gdg`, LIVE).

## What shipped

**Phase 0 — Observability**
1. ✅ Pure-ASGI timing middleware (`cloud/observability.py`, wired in `cloud/main.py`): per-request
   structlog line (route template, method, status, duration_ms) + `Server-Timing` header. >250 ms
   always logged, ~1% sampling below.
2. ✅ `scripts/latency-report.sh` — p50/p95/max per endpoint from Render edge logs.
   Note: the Render logs API now rejects `--limit` >~500 with HTTP 400; run `latency-report.sh 500`.
3. ✅ Outbound `httpx` timing via event hooks on the shared clients (`gateway_proxy.py`, `proxy.py`).

**Phase 1 — 35-second stalls**
4. ✅ Fly-status reconciliation sweep (`cloud/runtime/reconcile.py`): agents whose machine is gone
   are marked `error` with reason "Machine no longer exists (reconciler)".
5. ✅ Fail-fast wake in `cloud/api/proxy.py`: machine-existence check before wake, `event.set()`
   always in `finally` + success flag, waiter timeout 30 s → 10 s.
6. ✅ Dashboard identity fix (`cloud/ui/src/pages/Dashboard.tsx`): attempted-set ref stops the
   retry storm; identity fetched once per card.

**Phase 2 — Per-request overhead**
7. ✅ Gateway proxy session collapse + `get_service` TTL cache (`gateway_proxy.py`, `gateway/registry.py`).
8. ✅ Pool tuning in `cloud/db/session.py` (`pool_size`, `max_overflow`, `pool_pre_ping`, `pool_recycle=300`).
9. ✅ Short-TTL auth cache in `cloud/auth/deps.py` (session→user lookups).
10. ✅ `--workers 2` in `cloud/Dockerfile`.
11. ✅ SPA `BaseHTTPMiddleware` replaced with mounted `StaticFiles` + 404→index fallback,
    `Cache-Control: public, max-age=31536000, immutable` on hashed assets.
12. ✅ `_list_luna_branches` parallelized with `asyncio.gather`.

**Phase 3 — Hygiene / cost**
13. ✅ `cloud/render.yaml` synced to reality: web `standard`→`starter` (2 workers fit 512 MB;
    upgrade deliberately if RSS grows), DB `starter`→`accelerated-16gb`.
14. ✅ Deleted `luna-service-cp-upgrade-clone-5d9c` (`dpg-d97anrpkh4rs73fgqmp0-a`) after verifying no
    service env referenced it; suspended the idle `luna` Render service (`srv-d8cu5hpkh4rs738ao9g0`).
15. ⏸ `usage_events` retention/rollup — **not done**, deliberate deferral (needs a data-retention
    decision; no latency impact).

## Verification (production, 2026-07-09)

- Tenant image `0.33.005` built via admin API + GH workflow (90 s, warm cache); test agent
  `vaselin-speed-test-005` provisioned and verified in a real browser (see dojo results in the
  companion summary).
- `scripts/latency-report.sh 500` after deploy:
  - `GET /api/auth/me` p50 **19 ms** (baseline 1.2 s).
  - `GET /api/agents` **31 ms**; dashboard settles in one fetch round, **0 extra API calls** in the
    6 s after settle (retry storm gone).
  - Ghost agents (Test 0.19.00x) show reconciler error + Retry in the UI; per-card identity probes
    to dead agents fail fast (~1 s, 401, once) instead of 35 s stalls.
  - Warm proxied `/a/{slug}/api/p/plugin-approvals/` ~**300–420 ms** edge-to-edge
    (baseline p50 1545 ms). Cold first-hit on a freshly provisioned agent is still 1–3 s
    (plugin first-load + pool warm-up) — expected.
- `Server-Timing` present on every response; proxied responses carry two entries
  (tenant app + control plane), so the split is visible in DevTools.
- SSE streaming unaffected: `/api/events` stays open (uncompressed, `no-cache`), chat streams fine
  with 2 workers.
- Cloud tests: **241 passed, 1 skipped**. UI build green.

## Deviations / notes

- render.yaml decision (item 13): stayed on `starter` instead of upgrading to `standard` — the
  2-worker setup fits, and a paid upsize should be Roy's call.
- Pushes to `main` trigger a `deploy_hook` deploy despite `autoDeploy: no` in Render settings —
  the API-triggered deploy of `18c6124` superseded it; be aware every push deploys in practice.
- Image `0.33.005` is **not** promoted to main (`is_main=false`); existing agents remain on their
  versions. Promote via `POST /api/admin/images/{id}/promote-main` when satisfied.
- Roy's gateway `extra_env` WIP (uncommitted in `gateway_admin_routes.py`, `models.py`,
  `provision_env.py`, `test_gateway.py`, `main.py`) was left untouched and excluded from commits.
