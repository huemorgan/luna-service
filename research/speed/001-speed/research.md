# 001 — Why Luna Is Slow: Production Performance Research

Date: 2026-07-09
Scope: production only (Render + Fly). Everything below was measured against live prod or verified in code with file:line references. No code was changed.

---

## 1. Executive summary

Luna is slow in production for five compounding reasons, ranked by impact:

1. **Ghost agents + a dashboard retry loop turn every dashboard load into a 35-second stall storm.** Agents whose Fly machine no longer exists are still `running` in the DB. The dashboard fetches each agent's identity through the tenant proxy; for ghost agents the request hangs ~35 s (wake-lock wait), and a React dependency-array loop re-fires the failed fetches every time another one resolves — measured 7 requests × 35 s per ghost agent per page view.
2. **The tenant runtime opens a brand-new cross-provider Postgres connection for every query (`NullPool`).** Fly machines (sjc) connect to Render Postgres (Oregon) over the public internet with a full TCP+TLS+auth handshake per session, and a typical `/api/p/*` request opens 3+ sessions (middleware guard, auth, route). Verified live: 25 running machines, **zero** open connections on the tenant DB. This is the main reason healthy-agent API calls take 1.5–2.5 s p50.
3. **Everything runs on one uvicorn worker on a 0.5-CPU Render Starter instance.** One event loop on `luna-service` serves the marketing site, admin UI, the LLM credential proxy (300 s streams), and the reverse proxy for every tenant request. One event loop on each tenant machine serves the UI, SSE streams, and the agent loop.
4. **Chat time-to-first-token is serialized behind network round trips:** memory-recall embedding call (measured 1.3 s through the gateway proxy), optional condense LLM call, history re-SELECT, agent rebuild — all before the first token streams.
5. **Zero latency observability.** Neither app logs request durations; there is no timing middleware, no slow-query logging. The only per-request latency signal in prod today is Render's edge log field `responseTimeMS` — which is what this research used.

Not the problem: CPU/memory saturation (all services idle at <1 % CPU, <200 MB RAM over 24 h), cross-region placement (Fly sjc ↔ Render Oregon is ~20 ms), Postgres plans (control-plane DB is `accelerated_16gb`).

---

## 2. Production topology (verified via Render API + Fly Machines API)

```
Browser (user, ~200 ms RTT to Oregon)
  │
  ▼
Render Oregon — luna-service (control plane, FastAPI, Starter: 0.5 CPU / 512 MB, 1 uvicorn worker)
  ├─ serves marketing + admin UI (Vite build via FastAPI middleware)
  ├─ /api/*           control-plane API (auth, agents, admin)
  ├─ /proxy/*         LLM credential gateway (tenants call this for every model/embedding call)
  └─ /a/{slug}/*      reverse proxy → tenant machine
        │
        ▼
Fly.io sjc — app "luna-agents": 25 machines, mostly shared-1×CPU / 1 GB
  (tenant Luna runtime: FastAPI + pydantic-ai, 1 uvicorn worker each)
        │
        ▼
Render Oregon Postgres — luna-tenant-prod (basic_256mb, max_connections=103)
  one database per tenant, reached via EXTERNAL hostname (public internet)
```

Render services (all Oregon):

| service | plan | notes |
|---|---|---|
| luna-service | **starter** (0.5 CPU/512 MB) | control plane + admin UI + gateway + proxy. `cloud/render.yaml:7` says `standard` — **live service is starter, config drift** |
| luna | starter | legacy/idle — ~zero traffic since Jul 4, 184 MB RSS. Candidate to suspend |
| luna-scheduler | starter | |
| luna-marketplaces | starter | |
| luna-wa-gateway | starter | |

Databases: `luna-service-cp` **accelerated_16gb** (upgraded Jul 8; leftover clone `luna-service-cp-upgrade-clone-5d9c` basic_256mb still running), `luna-tenant-prod` **basic_256mb** shared by all 25 tenants, plus luna-db (basic_1gb), luna-mp-db (pro_4gb), luna-scheduler-db, luna-wa-db (basic_256mb).

Fly machines: 25/25 `started`, `autostop: off, autostart: true, restart: always` ([fly_machines.py:231-247](cloud/runtime/fly_machines.py#L231-L247)), default guest shared-1×/1024 MB ([image_defaults.py:23-28](cloud/provisioning/image_defaults.py#L23-L28)). Two exceptions: one 4-CPU/4 GB, one 8-CPU/16 GB machine.

Note on method: I inventoried Render via its REST API and CLI rather than Playwright-driving dashboard.render.com — same data, scriptable, and reusable for ongoing tracking.

---

## 3. Measured production latencies

### 3.1 Render edge logs (`responseTimeMS`), luna-service, 30-min window on 2026-07-09

| endpoint | n | p50 | max |
|---|---|---|---|
| `GET /a/vaselin-test-0-19-*/api/p/plugin-identity/` (4 ghost agents) | 7 each | **~35,500 ms** | 36,052 ms |
| `GET /api/admin/luna/branches` | 1 | 11,992 ms | |
| `GET /a/<healthy agent>/api/p/plugin-identity/` (~12 agents) | 7–9 each | **1,450–2,400 ms** | 4,155 ms |
| `GET /api/auth/me` | 8 | **1,246 ms** | 2,491 ms |
| `POST /proxy/openai/embeddings` (memory recall, per chat turn) | 1 | 1,275 ms | |
| `GET /api/admin/admins` | 1 | 2,815 ms | |
| `GET /api/agents/<id>/upgrade-check` | 1 | 3,455 ms | |

Render's own latency metric for luna-service over 7 days: p50 typically 1–4 ms (static assets/health), but p99 series spikes to **4.6 s**. The service is bimodal: static is fine, anything touching DB/proxy/tenants is seconds.

### 3.2 Live probes (from user's location, ~200 ms RTT to Oregon)

| target | TTFB | note |
|---|---|---|
| `https://luna-service.onrender.com/` | 0.35–0.68 s | admin UI shell |
| `https://luna-agents.fly.dev/` (tenant UI direct) | **0.85–1.4 s** | just the index.html |
| tenant JS bundle (197 KB) | 0.9 s TTFB, **2.1 s total** | **served uncompressed**, no `Cache-Control`, via Python `FileResponse` |
| luna-service JS bundle | 0.4 s, brotli 134 KB | Render edge compresses; still no `Cache-Control: immutable` |

### 3.3 Resource utilization (Render metrics API, 24 h)

All Luna services: CPU avg ≤0.5 % of a core, max 6 %; memory 90–190 MB of 512 MB. Tenant Postgres: **1 connection open (my probe), 0 from the app** while 25 machines were running. **Slowness is per-request latency, not load. Upgrading machine plans alone will not fix this.**

---

## 4. Root-cause analysis

### 4.1 The dashboard 35-second storm (ghost agents × retry loop)

Chain of evidence:

1. Dashboard fetches `/a/{slug}/api/p/plugin-identity/` for every agent with `status === 'running'` ([Dashboard.tsx:104-115](cloud/ui/src/pages/Dashboard.tsx#L104-L115); same pattern in [AgentDetail.tsx:136](cloud/ui/src/pages/AgentDetail.tsx#L136)).
2. Four `vaselin-test-0-19-*` agents are `running` in the DB but have **no Fly machine** (verified: none of them appear in the Fly machines list). The DB status is never reconciled with Fly reality.
3. The proxy tries the machine, gets a connect failure, and calls `_try_wake_agent` ([proxy.py:225-241](cloud/api/proxy.py#L225-L241)). Concurrent requests for the same agent wait up to **30 s** on the wake lock ([proxy.py:79-85](cloud/api/proxy.py#L79-L85)); on failure the event is never `set()`, so every waiter burns the full 30 s. Result: ~35.5 s per request.
4. The React effect has `identities` in its dependency array and only skips agents already **successfully** resolved ([Dashboard.tsx:104-106](cloud/ui/src/pages/Dashboard.tsx#L104-L106)). Every time one identity resolves, the effect re-runs and **re-fires fetches for every agent that failed** — the logs show exactly 7 attempts per ghost agent in one session.

Net effect: one dashboard visit with 4 ghost agents ≈ 28 requests each pinned for ~35 s on a single-worker event loop that is also serving everything else. This alone can make the whole control plane feel dead.

### 4.2 Tenant runtime: NullPool + cross-provider DB (the healthy-agent 2 s)

- `luna/data/__init__.py:28-34`: `create_async_engine(url, poolclass=NullPool)` — **every** `session_scope()` opens a fresh asyncpg connection and closes it.
- Machines receive the **external** DB hostname `*.oregon-postgres.render.com` ([workflow.py:68](cloud/provisioning/workflow.py#L68)) — Fly sjc → public internet → Render Oregon, full TCP + TLS + Postgres auth per connection (~100–300 ms each).
- A single `/api/p/*` request pays this at least 3×:
  - `_plugin_disabled_guard` middleware runs on every `/api/p/*` request and does a **full-table `SELECT` of `plugin_rows`** on a fresh connection ([app.py:328-342](luna/plugins/plugin_api/app.py#L328-L342) → [loader.py:269-291](luna/plugins/loader.py#L269-L291)).
  - `get_current_user` re-SELECTs the user on every authenticated request ([app.py:360-375](luna/plugins/plugin_api/app.py#L360-L375)).
  - The route's own queries.
- Confirmed live: `pg_stat_activity` on the tenant cluster showed 0 application connections with 25 machines up — pure connect-per-request churn.

This stacks under the control-plane proxy hop: browser → Render (auth: 3 control-plane queries per proxied request, [proxy.py:44-68](cloud/api/proxy.py#L44-L68)) → Fly → 3+ fresh DB connections → back. 1.5–2.5 s p50 measured.

### 4.3 Linear vs parallel — where requests serialize

**Control plane (`cloud/`)** — routes are async, asyncpg throughout; the sync-DB-in-async-route problem does **not** exist. What is serial:

| path | serialization | ref |
|---|---|---|
| gateway proxy (every tenant LLM call) | 3–4 sequential DB sessions per request: service+token+policy+keys → catalog → key-mark → usage insert; pool is default size 5, untuned, no `pool_pre_ping` | [gateway_proxy.py:179,263,302,316](cloud/api/gateway_proxy.py#L179), [metering.py:58](cloud/gateway/metering.py#L58), [session.py:20](cloud/db/session.py#L20) |
| `get_service` | uncached DB read per proxy call (policy/catalog are TTL-cached; this one isn't) | [registry.py:89](cloud/gateway/registry.py#L89) |
| `/api/admin/luna/branches` | 2 GitHub API calls **per branch, serial** — the measured 12 s | [admin_routes.py:387-408](cloud/api/admin_routes.py#L387-L408) |
| agent metrics refresh (cold) | Fly describe → Fly volume → R2 stats, serial | [agent_routes.py:566-624](cloud/api/agent_routes.py#L566-L624) |
| provisioning env build | per-binding `get_service`+`has_active_key`+`resolve_keys` loop (N+1) | [provision_env.py:87-107](cloud/gateway/provision_env.py#L87-L107) |
| session auth | 1–3 uncached DB reads per authenticated UI request | [deps.py:20-72](cloud/auth/deps.py#L20-L72) |

**Tenant runtime (`luna/`)** — chat turn, before the first token streams:

1. insert user message; **re-SELECT the entire message history** and reconstruct it ([app.py:838-856](luna/plugins/plugin_api/app.py#L838-L856));
2. rebuild the whole agent object ([app.py:694-716](luna/plugins/plugin_api/app.py#L694-L716)) — identity/prompts/MCP gathered concurrently (good);
3. `asyncio.gather(recall, condense-check, disabled-plugins)` ([runtime.py:1337-1345](luna/agent/runtime.py#L1337-L1345)) — parallel with each other (good) but **all before first token**, and recall = embedding HTTP call routed **through the gateway proxy on Render** (measured 1.3 s) + pgvector query; condense may add a full LLM summarization call;
4. prompt re-assembled from all plugins every turn (parallelized since 008.9).

So a chat message pays: Fly→Render→OpenAI embedding round trip + several fresh DB connections + possible condense call, serially before streaming. **2–4 s of time-to-first-token is structural, independent of the model.**

Responses do stream properly (SSE via `EventSourceResponse`, [app.py:905-907](luna/plugins/plugin_api/app.py#L905-L907)); polling is not the transport.

### 4.4 Single worker, single loop

- luna-service: `uvicorn cloud.main:app` — no `--workers` ([cloud/Dockerfile:22](cloud/Dockerfile#L22)). This one process handles LLM streams up to 300 s ([gateway_proxy.py:50](cloud/api/gateway_proxy.py#L50)), tenant proxy streams (120 s), admin API, and static files.
- Every response — including streams — additionally passes through a `BaseHTTPMiddleware` SPA layer ([main.py:41-65](cloud/main.py#L41-L65)), which wraps bodies in an anyio memory-stream bridge (known Starlette streaming overhead) and stats the filesystem on 404s.
- Tenant runtime: same single-worker pattern ([luna/scripts/start.sh](luna/scripts/start.sh)); any CPU-bound span (JSON, prompt assembly, Python-cosine fallback) freezes all SSE streams on that machine.

### 4.5 UI delivery and behavior

- Tenant UI: Vite build with **no code splitting** ([luna/ui/vite.config.ts](luna/ui/vite.config.ts)), served file-by-file through a Python catch-all `FileResponse` with **no compression and no cache headers** ([plugin_webui/__init__.py:37-43](luna/plugins/plugin_webui/__init__.py#L37-L43)) — measured 197 KB uncompressed JS, 2.1 s. Fly's proxy does not compress for you; Render's edge does (admin UI got brotli).
- Page-load fan-out (tenant Shell): `authStatus` → `me` **sequential** ([App.tsx:22,51](luna/ui/src/App.tsx#L22)), then ~6 fetches + SSE; each `/api/p/*` call pays the middleware guard tax (§4.2).
- Polling on top of SSE: while a turn streams, ChatPanel polls **2 endpoints every 2 s** ([ChatPanel.tsx:754](luna/ui/src/views/ChatPanel.tsx#L754)); approvals every 30 s; marketplace upgrades every 60 s; optional second `topics=*` debug SSE stream ([debug.ts:42](luna/ui/src/lib/debug.ts#L42)).
- Admin UI: `fetch('/api/auth/me')` + `/api/agents` in parallel (good), then the per-agent identity fan-out (§4.1).

### 4.6 Startup cost (matters on every deploy/restart and machine wake)

Tenant boot: `alembic upgrade head` + `create_all` ×2 + `heal_additive_columns` inspecting every table + full plugin load ([luna_serve.py:26-77](luna/luna_serve.py#L26-L77), [heal.py:31-35](luna/data/heal.py#L31-L35)) — observed ~9 s app boot in Render logs, on top of Fly machine start. This is why any wake path costs tens of seconds. Control plane runs ~25 DDL statements per boot ([main.py:73-145](cloud/main.py#L73-L145)).

### 4.7 Latent risks (not currently biting, will bite)

- **Memory recall silent fallback**: if the pgvector expression index/cast fails, recall loads **all** memory rows and cosines 1536-dim vectors in Python per turn ([plugin_memory/__init__.py:180,220-233](luna/plugins/plugin_memory/__init__.py#L180)) — CPU/RAM spike on 1 GB machines. Worth verifying the HNSW index exists in each tenant DB.
- **`usage_events` unbounded growth** — one row per proxied LLM call, no retention/rollup ([models.py:249](cloud/db/models.py#L249)); budget check does windowed `COUNT(*)` ([policy.py:66-73](cloud/gateway/policy.py#L66-L73)).
- Tenant DB cluster is `basic_256mb` with `max_connections=103` shared by all tenants. Fine today (NullPool keeps connections at ~0); the moment tenants switch to pooling (recommended), 25 machines × pool_size must stay under ~100 — needs deliberate sizing or PgBouncer.
- Largest tenant DB is only 89 MB — data volume is not a factor yet.

---

## 5. How to track speed going forward (proposal)

Principle Roy stated: prefer logs over one-off instrumentation. Ordered accordingly:

### Tier 0 — already exists, use it today (no code change)
Render's edge log line for every request already carries `responseTimeMS`, path, status, requestID. A small script (like the one used for §3.1) can pull `render logs -r <srv> -o json`, join edge lines with route lines, and emit a p50/p95/max table per endpoint. Recommend: commit it as `scripts/latency-report.sh` and run it ad hoc or nightly. Limitation: it measures the Render hop only — it cannot see inside the tenant machine or split DB vs proxy vs LLM time.

### Tier 1 — surgical, permanent: one timing middleware per app (~30 lines each)
Add a pure-ASGI (not `BaseHTTPMiddleware`) timing middleware to `cloud/main.py` and the tenant app that logs one structured line per request — route template (not raw path), method, status, duration_ms, and coarse phase timings — and sets `Server-Timing` response headers so browser DevTools shows the backend split on every request with zero extra tooling. Sample slow requests only (e.g. log everything >250 ms, sample 1 % below) to keep log volume flat. This is the single highest-value observability change: it splits "proxy hop" vs "tenant app" vs "DB" forever.

### Tier 2 — DB and dependency visibility
- SQLAlchemy event hooks for connect-time and query-time; log connections that take >100 ms to establish (would have exposed NullPool immediately) and queries >200 ms.
- Time outbound `httpx` calls in gateway/proxy/embedding paths (one `event_hooks` registration per shared client) — separates "we were slow" from "OpenAI/Fly/GitHub was slow".

### Tier 3 — UI
- Log `web-vitals` (TTFB, FCP, LCP, INP) from both UIs to a `/api/vitals` endpoint (or just console+Server-Timing during dev sessions).
- One `fetch` wrapper that records per-endpoint client-observed latency; surfaces the retry-storm class of bug instantly.

Not recommended now: full OpenTelemetry/APM — overkill for a single-operator system; the above gives 90 % of the signal with ~100 lines total and no vendor.

---

## 6. Improvement backlog (ranked, with expected effect)

**Quick wins (hours, no architecture change):**
1. Reconcile agent status with Fly reality (periodic sweep: list machines, mark missing ones `error`) + make `_try_wake_agent` fail fast when the machine doesn't exist, and `set()` the wake event on failure so waiters don't burn 30 s ([proxy.py:79-117](cloud/api/proxy.py#L79-L117)). Kills the 35 s stalls.
2. Fix the Dashboard identity effect: fetch once per agent (track attempted, not just resolved; drop `identities` from the deps or use a ref) ([Dashboard.tsx:104-115](cloud/ui/src/pages/Dashboard.tsx#L104-L115)). Better: have the control plane cache identity per agent and serve it from `/api/agents` in one response — the per-card fan-out disappears entirely.
3. Replace tenant `NullPool` with a real pool (`pool_size=3-5, max_overflow=2, pool_pre_ping=True, pool_recycle=300`) ([luna/data/__init__.py:28-34](luna/data/__init__.py#L28-L34)). The cross-loop test concern is solvable with a per-loop engine. Expected: −0.5–1.5 s on every tenant API call. Size against `max_connections=103` on the shared cluster (25 machines × ~4 = borderline; consider per-machine pool_size 2–3 or PgBouncer).
4. Cache `get_disabled_plugin_names` in-process with a short TTL / invalidate-on-write ([loader.py:269-291](luna/plugins/loader.py#L269-L291)) — removes a full-table scan from every `/api/p/*` request.
5. `--workers 2` on luna-service + tune its DB pool accordingly ([cloud/Dockerfile:22](cloud/Dockerfile#L22)); the 512 MB Starter instance fits 2 workers at current ~105 MB RSS. Or upgrade the plan — but note §3.3: CPU is not the current bottleneck, isolation from long streams is.
6. Compress + cache tenant UI assets: serve `dist/` via `StaticFiles`, add `Cache-Control: immutable` on hashed assets, enable gzip/brotli (Starlette `GZipMiddleware` or pre-compressed files) ([plugin_webui/__init__.py:37-43](luna/plugins/plugin_webui/__init__.py#L37-L43)).
7. Parallelize `_list_luna_branches` GitHub calls with `asyncio.gather` ([admin_routes.py:387-408](cloud/api/admin_routes.py#L387-L408)) — 12 s → ~1 s.
8. Delete/suspend leftovers: `luna-service-cp-upgrade-clone-5d9c` DB, and decide the fate of the idle `luna` (luna-kp8e) Render service.

**Structural (days):**
9. Collapse gateway-proxy DB work to one session per request and TTL-cache `get_service`; batch key-mark + usage insert ([gateway_proxy.py](cloud/api/gateway_proxy.py), [registry.py:89](cloud/gateway/registry.py#L89)).
10. Replace the SPA `BaseHTTPMiddleware` with mounted `StaticFiles` + explicit 404 fallback route so proxy/LLM streams don't pass through it ([main.py:41-65](cloud/main.py#L41-L65)).
11. Cut chat TTFT: run memory-recall embedding against a cached/local path or start the LLM call optimistically while recall resolves; skip condense-check when history is short; cache the reconstructed history per conversation instead of re-SELECTing every turn ([runtime.py:1337-1345](luna/agent/runtime.py#L1337-L1345), [app.py:838-856](luna/plugins/plugin_api/app.py#L838-L856)).
12. Replace ChatPanel's 2 s poll with the SSE events it already subscribes to ([ChatPanel.tsx:754](luna/ui/src/views/ChatPanel.tsx#L754)).
13. Auth caching: short-TTL in-process cache for session-user lookups on both apps ([deps.py:20-72](cloud/auth/deps.py#L20-L72), [app.py:360-375](luna/plugins/plugin_api/app.py#L360-L375)). `/api/auth/me` at 1.2 s p50 is mostly this + starter-instance scheduling.
14. Sync `cloud/render.yaml` plans with reality (declared `standard`, live `starter`) and decide intentionally per service.

**Deliberately not proposed:** bigger Fly machines / Render plans as a first move — utilization data (§3.3) shows the fleet is idle; latency is architectural. Re-evaluate plans only after items 1–5 land and Tier-1 timing logs show where the remaining time goes.

---

## 7. Reproduction / method appendix

- Render inventory & metrics: `render services -o json --confirm`; `GET api.render.com/v1/metrics/{cpu,memory,http-latency?quantile=}`; `GET /v1/postgres`.
- Latency table: `render logs -r srv-d8g5pd42m8qs73ekk2b0 --limit 1000 -o json --confirm`, pair `responseTimeMS=` edge lines with adjacent uvicorn route lines, aggregate p50/p95/max per normalized path.
- Fly fleet: `GET api.machines.dev/v1/apps/luna-agents/machines` (token from luna-service env).
- Tenant DB live state: `psql` (read-only) against `luna-tenant-prod` external host — `pg_stat_activity`, `max_connections`, `pg_database_size`.
- Probes: `curl -w` TTFB/total against luna-service.onrender.com, luna-agents.fly.dev, and both JS bundles with `Accept-Encoding: gzip, br`.

Key service IDs: luna-service `srv-d8g5pd42m8qs73ekk2b0`, luna `srv-d8cu5hpkh4rs738ao9g0`, tenant DB `dpg-d8g5nim47okc73f0gl6g-a`, control-plane DB `dpg-d8g76av7f7vs73f2a6lg-a`, Fly app `luna-agents`.
