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

## Pending — Phase 2 (needs coordinated cross-repo releases)

Until these land, scheduler/playbook spend still folds into **Chat** (no
breakage; `job_id`/`channel` simply arrive NULL). Companion proposal already
pushed to luna `main`: `luna/plans/039.1-luna-service-channel-attribution/`.

- `luna/` core (submodule): add `channel` to `LLMCallContext` +
  `llm_call_scope` (inherited like `kind`); emit `x-luna-channel` +
  `x-luna-job-id`; fix the `root_action_type` vocabulary
  (`chat_turn`/`task_run` → `chat`/`background_run`) so the gateway stops
  storing NULL; carry origin into headless/muted turns.
- `luna-scheduler/plugin-scheduler` `_emit_fire`: stamp `channel="scheduler"`
  + trigger id when firing (both agent_prompt and playbook fires).
- plugin_playbooks runner: stamp `root_action_type="playbook_run"` + stable
  playbook id.

Header names are frozen and shared with `cloud/gateway/enforcement.py`
(`x-luna-channel`, `x-luna-job-id`, `x-luna-root-action-type`).
