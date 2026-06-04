# Phase 006 — Agent Detail Page

## Goal

From the dashboard, clicking an agent opens a **detail page** that shows everything we know about that Luna: where it lives, what it's using, what it costs, what it's done. Ship the easy stuff now (data we already have or that's one Fly API call away); stub the harder metering work as "Coming soon" tiles so the layout is final and we can fill cells in over time.

**Render = the management surface for one Luna. Fly = where the Luna actually runs.** This page is the bridge between them.

## What "Easy Now" vs "Coming Soon" Means

Three tiers based on cost-to-implement, not value:

| Tier | What | Why this tier |
|---|---|---|
| **Ship now** | Data already on the `agents` row + one `GET /machines/{id}` call to Fly | Zero new infra, zero new tables, zero new background jobs |
| **Ship now-ish** | One additional Fly metrics call + one R2 `ListObjectsV2` for storage size | Read-only API calls, cached 60s, no schema changes |
| **Coming soon** | Anything that needs metering: message counts, LLM spend, plugin spend, cost caps, activity hours, per-job cost | All require a metering pipeline (Luna → control plane events) which is its own phase |

Coming-soon tiles render as styled placeholders with a tooltip explaining what will appear and which phase delivers it. This keeps the final layout visible so we (and any future user) see the destination.

## Page Layout

```
┌─ Header ─────────────────────────────────────────────────────────────┐
│ 🌙 luna.com.ai > Dashboard > My Marketing Luna                       │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  My Marketing Luna                              [Open] [Stop] [⋯]   │
│  🟢 running · Created Jun 4, 2026 · Last active 12 min ago           │
│                                                                      │
│  ┌─ Identity & Routing ────────────────────────────────────────────┐ │
│  │ Slug              vaselin-marketing                              │ │
│  │ URL               luna.com.ai/vaselin-marketing                  │ │
│  │ Account           Vaselin's Workspace · free plan                │ │
│  │ Created by        vaselin@gmail.com                              │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ Compute (Fly Machine) ─────────────────────────────────────────┐ │
│  │ Machine ID        148e9032b50708                                 │ │
│  │ App               luna-tenants-prod                              │ │
│  │ Region            sjc (San Jose)                                 │ │
│  │ Image             registry.fly.io/luna-tenants-prod:dev-001      │ │
│  │ Size              shared-cpu-1x · 1024 MB     [Resize  Soon]     │ │
│  │ State             started · uptime 2h 14m                        │ │
│  │ Last started      2h 14m ago                                     │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ Storage ───────────────────────────────────────────────────────┐ │
│  │ Postgres schema   luna_user_vaselin_marketing                    │ │
│  │ Postgres host     luna-tenant-prod (Render, Oregon)              │ │
│  │ Volume            /workspace · 1 GB                              │ │
│  │ R2 prefix         tenant/vaselin-marketing/ · 0 B                │ │
│  │ Vault key         derived · ref vk_a1b2c3                        │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ Activity (Coming soon) ────────────────────────────────────────┐ │
│  │ ░░░  Messages this month       — coming in phase 008             │ │
│  │ ░░░  Tool calls                — coming in phase 008             │ │
│  │ ░░░  Active hours / day        — coming in phase 008             │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ Spend (Coming soon) ───────────────────────────────────────────┐ │
│  │ ░░░  LLM cost this month        — coming in phase 008            │ │
│  │ ░░░  Compute cost (Fly)         — coming in phase 008            │ │
│  │ ░░░  Storage cost               — coming in phase 008            │ │
│  │ ░░░  Cost per plugin            — coming in phase 008            │ │
│  │ ░░░  Cost cap                   — coming in phase 009 (billing)  │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ Recent errors ─────────────────────────────────────────────────┐ │
│  │ (none) — or last 3 entries from agents.error_message + audit_log│ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  Danger zone:  [Delete agent]                                        │
└──────────────────────────────────────────────────────────────────────┘
```

## What's in each tier

### Ship now (just render what we have)

All from the `agents` row + joins to `accounts` and `users` — no new data sources, no new fields:

- Name, slug, status, created_at, last_active_at, error_message, error_at
- Account name + plan + creator email
- `db_schema`, `runtime_kind`, `runtime_ref`, `internal_url`, `vault_key_ref`
- Derived: full URL (`luna.com.ai/{slug}`), Postgres host (from `CLOUD_TENANT_DB_HOST`), R2 prefix (`tenant/{slug}/`)

### Ship now-ish (one Fly API call + one R2 call, cached 60s)

- **`GET /v1/apps/{app}/machines/{id}`** → region, image, `config.guest` (cpu_kind / cpus / memory_mb), `state`, `created_at`, `events[]` for last_started / last_stopped
- **R2 `ListObjectsV2` on `tenant/{slug}/`** → object count + total bytes (single paginated call, cached)
- **Volume size** is config we set at provision — read from `agent.metadata` JSON (new column, see step 1)

These two calls add ~200-400 ms to a page load; we cache the result on the `Agent` row in a new `cached_metrics JSONB` column with a `cached_at` timestamp. Refresh on demand or when older than 60 s.

### Coming soon (placeholders only)

Each tile renders as a greyed card with the metric name, "Coming soon", and a tooltip with which phase delivers it. The Resize control is the same — disabled button with "Coming soon" badge.

The metering pipeline that fills these is **phase 008 — Metering & Telemetry**, and billing/cost caps are **phase 009 — Billing**. Out of scope here; this phase just makes the holes shaped right.

## Implementation Steps

### Step 1 — Backend: extend `Agent` model

**File:** `cloud/db/models.py`

Add two columns to `Agent`:

- `cached_metrics: Mapped[dict | None] = mapped_column(JSONB)` — Fly machine snapshot + R2 size
- `cached_metrics_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))`

Optional now, useful for everything later. Alembic migration: `add_agent_cached_metrics.py`.

We do **not** add per-agent metering columns now (messages, llm_cost, etc.) — those belong in a separate `usage_events` table that phase 008 owns.

### Step 2 — Backend: extend `GET /api/agents/{id}` and add `GET /api/agents/{id}/details`

**File:** `cloud/api/agent_routes.py`

- Keep `GET /api/agents/{id}` as the lightweight version (what the list page uses)
- Add **`GET /api/agents/{id}/details`** that returns everything the detail page needs in one payload:

```json
{
  "agent": { ...same as get_agent... },
  "account": { "slug": "...", "name": "...", "plan": "free" },
  "creator": { "email": "..." },
  "routing": {
    "public_url": "https://luna.com.ai/vaselin-marketing",
    "internal_url": "http://...vm.luna-tenants-prod.internal:8000"
  },
  "storage": {
    "postgres": { "host": "luna-tenant-prod...", "schema": "luna_user_..." },
    "r2": { "prefix": "tenant/vaselin-marketing/", "size_bytes": 0, "object_count": 0 },
    "volume": { "mount": "/workspace", "size_gb": 1 },
    "vault_key_ref": "vk_a1b2c3"
  },
  "compute": {
    "kind": "fly-machine",
    "machine_id": "148e9032b50708",
    "app": "luna-tenants-prod",
    "region": "sjc",
    "image": "registry.fly.io/luna-tenants-prod:dev-001",
    "size": { "cpu_kind": "shared", "cpus": 1, "memory_mb": 1024 },
    "state": "started",
    "last_started_at": "2026-06-04T17:53:00Z",
    "uptime_seconds": 8052
  },
  "metrics_cached_at": "2026-06-04T20:11:00Z",
  "coming_soon": {
    "activity": ["messages_this_month", "tool_calls", "active_hours_per_day"],
    "spend":    ["llm_cost", "compute_cost", "storage_cost", "cost_per_plugin", "cost_cap"]
  }
}
```

Logic:
1. Load Agent + Account + creator User
2. If `cached_metrics_at` is older than 60 s (or null), refresh: parallel `await asyncio.gather(fly_get_machine(), r2_list_prefix())`, store result on the row, commit
3. Compose the response above and return

The `coming_soon` lists let the frontend render the placeholder tiles from server-driven config, so adding/removing a tile in the future doesn't need a UI deploy.

### Step 3 — Backend: Fly + R2 helpers

**Files:** `cloud/runtime/fly_machines.py` (extend), `cloud/storage/r2.py` (new)

In `fly_machines.py` add:

```python
async def describe(self, handle: RuntimeHandle) -> dict:
    r = await self.client.get(f"/machines/{handle.ref}")
    r.raise_for_status()
    return r.json()  # full Fly machine record
```

In a new `cloud/storage/r2.py`:

```python
async def list_prefix_stats(prefix: str) -> dict:
    """Return {object_count, size_bytes} for an R2 prefix. Single ListObjectsV2 call, paginated."""
    ...
```

Both are read-only, no new credentials beyond what's already in `.env`.

### Step 4 — Frontend: `AgentDetail.tsx`

**Files:** `cloud/ui/src/pages/AgentDetail.tsx` (new), `cloud/ui/src/App.tsx` (add route `/dashboard/agents/:id`)

Components:

- `<DetailHeader>` — name, status pill, action buttons (Open, Stop/Start, more menu)
- `<InfoCard title="…">` — generic key/value list used by Identity/Compute/Storage
- `<ComingSoonCard title="…" tiles={[…]}>` — greyed card with metric labels and a `Coming soon · phase N` badge per row; tooltips explain the metric
- `<DangerZone>` — delete confirmation

Behavior:
- Fetch `GET /api/agents/{id}/details` on mount
- Show skeleton while loading
- Re-fetch every 10 s while `status === "provisioning"`, otherwise on user action
- "Resize" button rendered but `disabled` with `title="Coming soon — Phase 007"`

### Step 5 — Wire from Dashboard

**File:** `cloud/ui/src/pages/Dashboard.tsx`

Make each agent row link to `/dashboard/agents/{id}`. Keep the inline Open/Start/Stop actions on the list (they're handy); the detail page is for everything else.

### Step 6 — Audit log surfacing (cheap win)

We already write to `audit_log`. The "Recent errors" card on the detail page shows the last 3 entries where `target = agent.id` (or join via metadata). One extra SELECT, no new infra.

## Files Changed

| File | Change |
|---|---|
| `cloud/db/models.py` | `Agent.cached_metrics`, `Agent.cached_metrics_at` |
| `cloud/alembic/versions/00X_agent_cached_metrics.py` | Migration |
| `cloud/api/agent_routes.py` | New `GET /api/agents/{id}/details` |
| `cloud/runtime/fly_machines.py` | `describe()` |
| `cloud/storage/r2.py` | New — `list_prefix_stats()` |
| `cloud/ui/src/pages/AgentDetail.tsx` | New page |
| `cloud/ui/src/components/InfoCard.tsx` | New |
| `cloud/ui/src/components/ComingSoonCard.tsx` | New |
| `cloud/ui/src/pages/Dashboard.tsx` | Row → detail link |
| `cloud/ui/src/App.tsx` | Route |

## Tests

Dojo scenarios in `tests/006-agent-detail/`:

- `01-detail-page-shows-real-machine.md` — provision an agent, navigate to detail, verify Fly machine id / region / size shown match `fly machines list`
- `02-coming-soon-rendered.md` — verify Activity and Spend cards render as placeholders, not blank
- `03-r2-size-reflects-upload.md` — drop a file into the R2 prefix via the AWS CLI, reload detail page, byte count updates within cache window
- `04-stale-cache-refreshes.md` — wait 65 s, reload, verify `metrics_cached_at` moves forward
- `05-error-history.md` — break Fly creds, retry, verify the latest error appears in Recent Errors card

## Not in This Phase

| Punted to |  |
|---|---|
| **Phase 007 — Machine resize** | Actually changing CPU/memory on a live Fly Machine (Fly API supports it, but needs start→update→start dance + status surfacing) |
| **Phase 008 — Metering** | Messages, tool calls, LLM tokens, active hours — needs Luna→control-plane event pipeline (Postgres `usage_events` table + ingestion endpoint + Luna plugin) |
| **Phase 009 — Billing & cost caps** | Cost cap UI, Stripe wiring, plan upgrades, cost-per-plugin breakdown |
| **Phase 010 — Logs viewer** | Tail Fly logs into the detail page |
| **Multi-agent team admin view** | Operator/admin view of *all* agents across all accounts (separate `/admin` surface) |

## Definition of Done

- [ ] Clicking an agent on the dashboard opens its detail page within 1 s
- [ ] Every field in the Identity / Compute / Storage cards is populated from real data (no hardcoding)
- [ ] Fly machine size / region / image match what `fly machines list --app luna-tenants-prod` shows
- [ ] Activity and Spend cards render as Coming-Soon placeholders with the phase reference
- [ ] Resize button is visible but disabled with a "Coming soon" tooltip
- [ ] All `tests/006-agent-detail/` scenarios pass
- [ ] Live walkthrough on production: create an agent, browse its detail page, see real Fly + Render data
