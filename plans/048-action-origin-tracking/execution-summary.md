# 048 — execution summary

_2026-07-17_

## What shipped (luna-service — Phases 1, 3, 4)

The full luna-service side landed and is verified. It degrades gracefully:
scheduler/playbook sections stay empty and traffic folds into Chat until the
Luna + plugin releases (Phase 2) land.

### Phase 1 — Usage chart polish (UI)
`cloud/ui/src/pages/billing/UsagePage.tsx`:
- Removed the day-range filter entirely (`RangeKey`, today/7d/28d/custom
  buttons, custom date inputs, `rangeQuery`). Always requests `range=28d`;
  a "Last 28 days" label replaces the buttons. Luna filter select stays.
- Redesigned `BarChart`: height 40px (was 96), **no gridlines**, **no rounded
  bars** (dropped `rounded-t`), **half width** (`max-w-[50%]`), dropped the
  3-tick y-axis column and show the shared `y_max` once, top-left.
`cloud/api/billing_routes.py`: `y_max = max(peak, 200)` (`Y_MAX_FLOOR`),
replacing `_clean_ceiling` — tallest single-day bar across all sections sits
exactly at the top, floored at 200.

### Phase 3 — luna-service consumes new dimensions
- `cloud/gateway/enforcement.py`: ingests `x-luna-job-id` →
  `BillingContext.job_id` → `BillableEvent.job_id` (both the settled event and
  the would-block shadow row). `channel` + allow-listed `root_action_type`
  ingest unchanged.
- `cloud/api/billing_routes.py` `usage_channels`: reworked `bucket` into the
  **precedence** classification — scheduler → playbook_run → whatsapp →
  telegram → web — so each root action lands in exactly one bucket and section
  totals stay additive to the account total. Added a **Playbooks** section
  (playbook_run NOT in scheduler) with a per-playbook breakdown, mirroring the
  scheduler per-trigger split via a shared `_split()` helper. Section list is
  now `web, scheduler, playbooks, whatsapp, telegram`. The scheduler section
  keeps a `triggers` alias alongside the new generic `items` for back-compat.
- `cloud/ui/src/pages/billing/api.ts`: `ChannelItem`, `items` on
  `ChannelSection`, `playbooks` in `sections`.
- UI: new **Playbooks** `ChannelCard` + generalized `ItemBreakdown`
  (expandable per-trigger / per-playbook), replacing `SchedulerTriggers`.

### Phase 4 — tests
- `cloud/tests/test_billing_customer_api.py`: seed now includes a scheduled
  playbook (precedence → scheduler) and a user playbook (→ playbooks); asserts
  the 5 buckets, non-overlapping additive totals, per-trigger + per-playbook
  splits, `y_max = max(peak, 200)`, plus a `y_max` floor test. 
- `cloud/tests/test_gateway_billing.py`: asserts `x-luna-channel`,
  `x-luna-job-id`, and a corrected `x-luna-root-action-type` (`scheduled_run`)
  are ingested. **72 passed** across both files.
- Dojo (`tests/048-action-origin-tracking/dojo_action_origin.py`, headless
  Playwright on real Postgres): S1 no range filter / 28d fixed, S2 five
  sections shared scale, S3 scheduled playbook under Scheduled (not Playbooks)
  + expandable, S4 square/gridline-free/half-width bars, S5 API shape +
  precedence totals + y_max. **All pass.** Screenshots under
  `tests/048-action-origin-tracking/results/`.

## What we discovered

- The 046 dojo seed used `source_idempotency_key="dojo046:{cid}"`, which the
  post-046 undercount fix's join (`source_idempotency_key = logical_call_id ||
  ':1'`) no longer matches. Fixed the seed to `"{cid}:1"` and updated its
  section-set assertion to include `playbooks` so the 046 harness stays valid.
- Precedence is implemented as an ordered SQLAlchemy `case` (first arm wins),
  so a scheduled playbook (channel=scheduler AND root_action_type=playbook_run)
  correctly stays under Scheduled. The playbooks per-item query mirrors this
  with `channel.is_distinct_from("scheduler")` so NULL-channel playbook runs
  still count.

## Phase 2 — DONE (Luna core + plugins)

Luna plan: `luna/plans/039.2-luna-service-action-origin-stamping/`.

- **luna/ core → 0.38.002 (commit 5fc8b43, pushed to `main`)**:
  `channel` + `job_id` on `LLMCallContext` / `llm_call_scope` (inherited down
  the chain); `headers_for_current_call()` emits `x-luna-channel` +
  `x-luna-job-id`; `MeteringModel._scope()` prefers an outer turn scope's origin
  over per-turn defaults; web `stream` → `root_action_type="chat"` +
  `channel="web"`; headless `run_turn` → `background_run` (fixes the
  `chat_turn`/`task_run` NULL-vocab bug); new SDK helper
  `luna_sdk.billing_origin_scope()`. Tests: 039 phase01/02 extended, 56 green.
- **luna-scheduler/plugin-scheduler → 0.3.1 (commit 5e343f3, pushed)**:
  `_emit_fire` wraps both fire kinds in `billing_origin_scope(channel="scheduler",
  root_action_type="scheduled_run", job_id=trigger_id)`. 32 green.
- **plugin-playbooks → 0.3.1 (commit af1e275, COMMITTED, push BLOCKED)**:
  runner wraps `_execute_steps` in `billing_origin_scope(
  root_action_type="playbook_run", job_id=playbook.name,
  prefer_outer_job_id=True)`. 8 green. **Push denied**: remote is
  `huemorgan2/plugin-playbooks`; the available `huemorgan` token is a
  non-collaborator (403). Owner must push + republish.

### Deploy status

- Luna image **v0.38.002** (git 5fc8b43) built from `main` via the admin Images
  page, set as Main, and **all 25 agents migrated**. This alone fixes the
  `root_action_type=NULL` bug for **all** turns and makes web chat correctly
  `channel=web` / `chat`. luna-service pointer: commit 5634377.
- Build-infra fix: the first build failed at recursive submodule checkout —
  `luna-marketplaces/luna` pinned a GC'd luna commit (f9bbbaf, "not our ref").
  The workflow file couldn't be edited (token lacks `workflow` scope), so
  instead bumped luna-service's `luna-marketplaces` pointer to c8c33b6 (already
  repointed its nested luna to live history) — commit 2db361a. Rebuild
  succeeded.
- **Remaining**: scheduler/playbook attribution needs the plugin releases to
  reach hosted agents (marketplace republish + per-agent plugin update).
  Scheduler plugin is pushed; playbooks plugin is committed but unpushed
  (huemorgan2). Until an agent runs the new plugin builds, its
  scheduled/playbook spend keeps folding into Chat (no breakage).

Header names are frozen and shared with `cloud/gateway/enforcement.py`
(`x-luna-channel`, `x-luna-job-id`, `x-luna-root-action-type`).
