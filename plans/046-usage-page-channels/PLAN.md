# 046 — Usage page redesign + per-channel credit attribution

## Goal

Split the customer **Billing** and **Usage** surfaces into two separate
top-bar sections, and rebuild the Usage page as a set of per-channel
28-day credit bar charts (web chat, scheduled triggers, WhatsApp,
Telegram) sharing one y-scale, filterable per Luna. Delete the Status
tab, drop the tab bar, and remove the actions list + "where credits
went" groupings.

The blocker discovered in research: **billing data has no channel
dimension.** An inbound WhatsApp or Telegram message produces a
`chat` action that is indistinguishable from a web message in
`billable_events`. So the core of this plan is adding a `channel`
dimension stamped at the source in Luna, threaded through the gateway
into `billable_events`, and aggregated by a new usage endpoint.

## Repos touched

| Repo | Role | Change |
|------|------|--------|
| `luna-service/` (owns this plan) | control plane | gateway header ingest, `billable_events.channel` column + migration, usage aggregation endpoints, UI restructure |
| `luna/` (submodule, READ-ONLY) | agent core | stamp `x-luna-channel` at turn entry. Ships as a **companion proposal** doc pushed to luna `main` — no code committed by us until the Luna team/user approves. |

`luna/` is read-only for implementation (AGENTS.md). We author a
proposal at `luna/plans/{n}-luna-service-usage-channels/` and the actual
Luna code lands via the luna-submodule-changes process. Until Luna
stamps the channel, WhatsApp/Telegram bars render empty ("no channel
data yet") and web chat shows all interactive chat.

---

## Channel taxonomy (the contract)

New optional field on a logical call, values (frozen, lowercase):

- `web` — Luna web chat UI (interactive, human at keyboard)
- `whatsapp` — inbound via the WhatsApp gateway
- `telegram` — inbound via the Telegram gateway
- `scheduler` — fired by a scheduled trigger (no human channel)
- `api` — programmatic / direct API callers
- `null`/unknown — legacy rows before this ships, and anything unstamped

Header name: **`x-luna-channel`** (frozen contract, mirrors the existing
`x-luna-*` set in `luna/luna/llm/context.py` ↔
`cloud/gateway/enforcement.py`).

Usage page section → filter mapping (all keyed on `channel`, NOT
`root_action_type` — see finding below):

1. **Chat (web)** → `channel = web`. Interactive web engagement and
   everything derived from it (playbook/background runs that inherit the
   turn's channel via nested `llm_call_scope`).
2. **Scheduled triggers** → `channel = scheduler`. Accumulated total +
   expandable per-trigger breakdown.
3. **WhatsApp** → `channel = whatsapp`.
4. **Telegram** → `channel = telegram`.

**Why key Scheduled on `channel`, not `root_action_type = scheduled_run`:**
a scheduled trigger that runs a playbook opens a *nested* scope that
overrides `root_action_type` (→ `playbook_run`/`task_run`) but inherits
`channel`. Keying on `channel = scheduler` keeps the whole
trigger→playbook→derived chain in the Scheduled bucket automatically.
`channel` = the stable "who initiated this" tag; `root_action_type` =
"what kind of step", which changes down the chain.

### ⚠ Finding: `root_action_type` is currently mismatched (effectively null)

The gateway accepts `root_action_type` ∈
`{chat, playbook_run, scheduled_run, background_run, forge_job}`
(`cloud/gateway/enforcement.py:72`). But Luna's runtime only ever emits
`"chat_turn"` (`luna/luna/agent/runtime.py:1698`) or `"task_run"`
(`:1386`) — **neither is in the accepted set**, so the gateway coerces
both to `null`. So today NO customer traffic is classified by
`root_action_type`; the `scheduled_run` label is never populated. This
must be fixed in the same Luna change that adds `channel` (Phase 1), or
the Scheduled section stays empty regardless of channel work.

---

## Phase 1 — Luna companion proposal (channel at the source)

Deliverable: `luna/plans/{n}-luna-service-usage-channels/PROPOSAL.md`
(proposal only, pushed to luna main).

Content of the proposal:

- Add `channel: str | None` to `LLMCallContext` + `llm_call_scope`
  (`luna/luna/llm/context.py`), inherited by nested scopes exactly like
  `root_action_id`/`root_action_type`.
- Emit `x-luna-channel` in `headers_for_current_call()`.
- Set the channel at each **turn entry point**:
  - web chat API handler → `web`
  - WhatsApp plugin/gateway inbound → `whatsapp`
  - Telegram plugin/gateway inbound → `telegram`
  - scheduler-fired runs → `scheduler`
  - programmatic → `api`
- Thread through `MeteringModel` (`luna/luna/llm/metering.py`) like the
  other context fields.
- **Also fix `root_action_type`** to emit values in the gateway's frozen
  set. Today the runtime emits `"chat_turn"`/`"task_run"` which the
  gateway drops to null (see finding above). Map to
  `chat | playbook_run | scheduled_run | background_run | forge_job` so
  action-type breakdowns work again. Not strictly required for the 4
  channel bars (those key on `channel`), but it's the same file/change
  and unblocks the existing `/usage/breakdown` action-type view.

We do NOT edit `luna/` code in this plan — the proposal is the
deliverable. The luna-service side is built to accept the header the
moment Luna starts sending it, and degrade gracefully until then.

## Phase 2 — Gateway ingest + schema

`luna-service`:

- `cloud/gateway/enforcement.py`: read `x-luna-channel`, validate
  against the frozen set (unknown → `null`), carry on `BillingContext`,
  and persist onto every `BillableEvent` it writes (both the pre-upstream
  reservation row and the per-attempt rows).
- `cloud/billing/models.py`: add `channel: Mapped[str | None]` to
  `BillableEvent` with an index supporting `(account_id, event_at,
  channel)` aggregation.
- Alembic migration: **add column nullable, no backfill destruction.**
  Existing rows keep `channel = NULL` (surfaced as "unknown/web-legacy"
  in the UI). DATA PRESERVATION: additive only, no drop/rewrite.

## Phase 3 — Usage aggregation endpoint(s)

`cloud/api/billing_routes.py`:

- New `GET /api/billing/usage/channels?range=28d&agent_id=` returning,
  for each of the 4 sections, a 28-day daily trend of credits plus a
  section total. Shared shape:
  ```json
  {
    "range": {"since": "...", "until": "..."},
    "y_max": 200,                    // shared axis ceiling across sections
    "sections": {
      "web":       {"total": 1234, "trend": [{"day":"2026-06-20","credits":42}, ...]},
      "scheduler": {"total": 88,   "trend": [...], "triggers": [
          {"key":"...", "name":"Morning digest", "total": 40, "trend":[...]}
      ]},
      "whatsapp":  {"total": 0, "trend": [...]},
      "telegram":  {"total": 0, "trend": [...]}
    }
  }
  ```
  - `y_max` computed once across all sections (clean 1/2/2.5/5×10ⁿ ceil,
    reuse the existing `trendCeil` logic) so a 10-max section renders
    short next to a 200-max section — per the requirement.
  - Credits attributed via the same `RatedCharge` ⋈ first-`BillableEvent`
    join already used by `/usage/breakdown`, grouped by `channel`. The
    scheduler section = `channel = scheduler` (not `root_action_type`).
  - `scheduler.triggers`: group scheduled charges by trigger identity
    (`job_id`, else `root_action_id`); resolve a human name from the
    scheduler where available (fallback to the id). Per-trigger 28-day
    trend included so the UI can expand each one.
  - `agent_id` optional filter → single-Luna view.
- Keep `range` support but default the page to `28d` (28-day = 4 weeks,
  per workspace time-periods rule; label "28 days").
- Retire from the UI's usage flow: `/usage/breakdown` and
  `/usage/actions` calls (endpoints can stay server-side for now; the UI
  stops using them). Keep `/usage/summary` for the per-Luna limits
  editor + headline stats.

## Phase 4 — Frontend: separate Billing and Usage

`cloud/ui`:

- **Routing** (`App.tsx`): add `/dashboard/usage` (new `UsagePage`),
  keep `/dashboard/billing` for billing only.
- **Top bar**: Dashboard header gets two entries — **Usage** and
  **Billing** — as separate links/sections (not tabs). Mirror on both
  pages' headers.
- **Billing page** (`billing/BillingPage.tsx`):
  - Delete the Status tab entirely (balance/sources/hosting/lots move…):
    decision — **fold the essential Status content (balance stats,
    credit sources, hosting, lots) into the single Billing page** above
    the packages, since Status is being removed as a *tab* but the
    balance info still belongs somewhere. Remove the `TABS` bar and
    `?tab=` handling. Billing = balance summary + packages + statement.
  - Remove all Usage-tab code from this file.
- **New `UsagePage`** (`billing/UsagePage.tsx`):
  - Top **filter bar**: a Luna pulldown (All Lunas + each Luna). Reads
    `?agent=` from the query string; a card's Usage button deep-links
    here pre-filtered.
  - Four stacked sections in order: Chat, Scheduled triggers, WhatsApp,
    Telegram. Each is a 28-day bar chart (reuse the existing bar/axis
    component), **all sharing `y_max`** from the endpoint.
  - Scheduled section: one accumulated bar chart + a collapsible list of
    triggers, each expandable to its own bar chart and total.
  - Empty channel (no data yet) renders the axis + "no activity" rather
    than disappearing, so the 4 sections are always present.
  - Keep the per-Luna limits editor (owner-only) on this page.
- **Luna cards** (`Dashboard.tsx` `AgentCard`): add a **Usage** button →
  `/dashboard/usage?agent={id}`, showing only that Luna's credits.

## Phase 5 — Tests (devprocess)

- `tests/046-usage-page-channels/` dojo scenarios (LLM-run in browser):
  1. Top bar shows Usage and Billing as separate sections; clicking each
     lands on the right page; no tab bar; no Status tab anywhere.
  2. Usage page shows 4 sections, all with a 28-day axis, shared y-scale
     (seed data so one section dwarfs another; verify the small one
     renders short, not full-height).
  3. Scheduled section expands to per-trigger charts.
  4. Luna card Usage button deep-links filtered; the pulldown switches
     Lunas and the numbers change.
  5. Billing page has balance + packages + statement, no usage content.
- Backend unit tests for `/usage/channels`: channel grouping, shared
  `y_max`, per-trigger split, `agent_id` filter, legacy `NULL` channel
  handling.
- Gateway test: `x-luna-channel` ingested + persisted; unknown value
  coerced to null; absent header → null (no crash).

---

## Decisions / open questions

- **Status content home**: folding balance/sources/hosting/lots into the
  single Billing page (recommended above). Alternative: put balance
  stats on the Usage page header. Confirm before Phase 4.
- **Scheduled trigger names**: best-effort from scheduler metadata;
  fall back to the trigger id. If no clean name source exists, ship ids
  first and improve later.
- **Legacy rows** (`channel = NULL`): shown under Chat (web) as the
  safest bucket, or a separate "unattributed" note. Default: fold into
  Chat, note it in copy.

## Non-destructive guarantees

- Migration is additive (new nullable column + index). No column/table
  drops, no row rewrites.
- Old `/usage/breakdown` and `/usage/actions` endpoints remain
  server-side (only the UI stops calling them), so nothing else that may
  depend on them breaks.
