# 048 — Track the origin of Luna actions (triggers + playbooks) + Usage chart polish

## Goal

Two things:

1. **Attribute spend by its true origin.** Today every LLM call — a web
   chat turn, a scheduled trigger firing daily, a playbook run — reaches
   the billing gateway looking identical, so the Usage page dumps
   everything into **Chat**. Scheduled triggers and playbooks (which the
   user says are the majority of spend) read **0 cr**. Fix the pipeline so
   luna-service can tell *what initiated* each action and break spend down
   by **scheduled triggers** and **playbook calls** (in addition to the
   existing web/WhatsApp/Telegram channels), with per-trigger and
   per-playbook detail.

2. **Tighten the Usage charts** (pure UI, ships immediately): drop the
   day-range filter, shrink the graphs, remove gridlines and rounded bar
   corners, halve the 28-day plot width, and use one shared y-axis =
   `max(all sections, 200)` so at least one bar always reaches the top and
   everything shares the same height scale.

## Root cause (confirmed)

A scheduled trigger fires: luna-scheduler → luna-service relay
(`cloud/api/scheduler_routes.py`) → `plugin-scheduler` on the agent → a
**muted turn inside the Luna agent** → LLM calls back out through our
gateway. Those calls are emitted *inside the agent process* and Luna tags
them exactly like web chat:

- `root_action_type` is `"chat_turn"` / `"task_run"`
  (`luna/luna/agent/runtime.py:1698, :1386`) but the gateway only accepts
  `{chat, playbook_run, scheduled_run, background_run, forge_job}`
  (`cloud/gateway/enforcement.py:72`) → stored **NULL**.
- **No `x-luna-channel`** header exists yet
  (`luna/luna/llm/context.py:80-94`).

So no field in `billable_events` distinguishes a scheduled/playbook run
from web chat. Attribution is impossible without stamping origin **inside
Luna**. (Full trace: subagent investigation, and plan 046 "Finding".)

## Two orthogonal dimensions

We already conceived one; this plan formalizes both:

| Dimension | Header | Values | Meaning | Stable down the chain? |
|-----------|--------|--------|---------|------------------------|
| **channel** (origin surface) | `x-luna-channel` | `web` / `whatsapp` / `telegram` / `scheduler` / `api` | who/what *initiated* the work | **Yes** — inherited by every nested scope |
| **root_action_type** (kind of step) | `x-luna-root-action-type` | `chat` / `playbook_run` / `scheduled_run` / `background_run` / `forge_job` | what *kind* of action this is | No — changes as the chain derives sub-work |
| **action id** (per-item) | `x-luna-root-action-id` (+ optional `x-luna-job-id`) | opaque stable id | which conversation / trigger / playbook | bound once at the top |

**Usage taxonomy — one bucket per root action (mutually exclusive, no
double counting), by precedence:**

1. `channel = scheduler` → **Scheduled triggers** (even if it runs a
   playbook — the whole trigger→playbook→derived chain stays here).
   Per-trigger breakdown keyed on the trigger id.
2. else `root_action_type = playbook_run` → **Playbooks** (user- or
   chat-initiated playbook runs). Per-playbook breakdown keyed on the
   playbook/action id.
3. else `channel = whatsapp` → **WhatsApp**
4. else `channel = telegram` → **Telegram**
5. else → **Chat** (web + legacy NULL).

This keeps section totals additive to the account total and matches "the
origin of Luna actions". Double-count caveat is resolved by the ordered
precedence (scheduler wins over playbook).

## Repos touched

| Repo | Change | Ships via |
|------|--------|-----------|
| `luna-service/` (owns this plan) | y_max rule + chart redesign; gateway ingest `x-luna-job-id`→`billable_events.job_id`; `usage_channels` precedence classification + Playbooks section + per-playbook/per-trigger; tests | this repo, deploy to Render |
| `luna/` (submodule, **needs explicit go**) | add `channel` to the LLM scope + emit `x-luna-channel`; fix `root_action_type` vocabulary; carry origin/action id into headless/muted turns | luna-submodule-changes process |
| `luna-scheduler/plugin-scheduler` | pass `channel="scheduler"` + trigger id when firing (`_emit_fire`) | that repo's publish flow |
| plugin_playbooks (playbook runner) | set `root_action_type="playbook_run"` + stable playbook id when a playbook runs | that plugin's publish flow |

`luna/` is normally read-only. The user said "lets fix that" → treat Luna
code changes as approved for this plan, executed via the
luna-submodule-changes skill. Until the Luna + plugin releases land,
luna-service degrades gracefully (scheduler/playbook sections stay empty,
everything folds into Chat) — exactly today's behavior.

---

## Phase 1 — Usage chart polish (UI only, ship first, no Luna release)

`cloud/ui/src/pages/billing/UsagePage.tsx`:

- **Remove the day-range filter** entirely (`RangeKey`, the today/7d/28d/
  custom buttons, `customStart/End`, `rangeQuery`). Always request `28d`.
  Query becomes `?range=28d(&agent_id=…)`.
- **Redesign `BarChart`:**
  - much smaller: `height` ~40px (from 96).
  - **no horizontal gridlines** — delete the tick `<div>`s at
    `UsagePage.tsx:59-62`.
  - **no rounded bars** — drop `rounded-t` (`:66`).
  - **half width** — cap the plot area to ~50% (e.g. wrap the bars row in a
    `max-w-[50%]` / fixed narrower container) so 28 days occupy half the
    card width.
  - drop the 3-number y-axis column; optionally show the single shared
    `yMax` value once (small, top-left) so the scale is legible without
    gridlines.
  - keep the first/last date labels small.
- Bars keep `minWidth` small and square; with 28 bars in half width they
  read as thin ticks — intended.

`cloud/api/billing_routes.py` `usage_channels`:

- **y_max rule:** replace `_clean_ceiling(peak)` (`:773`) with
  `y_max = max(peak, 200)`. No "nice" rounding — the tallest single-day bar
  across *all* sections sits exactly at the top, and the floor is 200 so a
  quiet account still scales against 200 (nothing balloons a 3-credit day
  to full height).

These are safe, self-contained, and give the user the visual they asked
for immediately, before the origin backend lands.

## Phase 2 — Luna stamps origin (needs luna + plugin releases)

`luna/luna/llm/context.py`:

- Add `channel: str | None` to `LLMCallContext` and `llm_call_scope(...)`,
  **inherited** by nested scopes exactly like `kind` (so a
  trigger→playbook→derived chain keeps `scheduler`). Update
  `headers_for_current_call()` to emit `x-luna-channel` when set, and
  optionally `x-luna-job-id` for a stable trigger/playbook id.

`luna/luna/llm/metering.py` + `luna/luna/agent/runtime.py`:

- Thread `channel` (and corrected `root_action_type`) through
  `MeteringModel` / `_build_reasoning_model`. Fix the vocabulary:
  - web `stream` (`runtime.py:1698`): `root_action_type="chat"`,
    `channel="web"`.
  - headless `run_turn` (`:1386`): `root_action_type="background_run"` by
    default; **accept `channel` + `root_action_type` + action id from the
    caller** so the scheduler/playbook entry can override.

`luna/luna/agent/muted.py` + `luna/luna/plugins/context.py`:

- Extend `send_muted_message` / `run_turn` to accept an origin
  (`channel`, `root_action_type`, action id) and bind it on the scope for
  the whole turn.

`luna-scheduler/plugin-scheduler` `_emit_fire`:

- `agent_prompt` fires → `send_muted_message(..., channel="scheduler",
  root_action_type="scheduled_run", job_id=trigger_id)`.
- `playbook` fires → run the playbook with `channel="scheduler"` +
  trigger id (channel precedence keeps it in the Scheduled bucket).

plugin_playbooks runner:

- When a playbook runs (any origin), set
  `root_action_type="playbook_run"` and a stable playbook id on the scope,
  so user-initiated playbooks land in the **Playbooks** section while
  scheduler-initiated ones stay under **Scheduled triggers** (precedence).

Contract mirrors: header names are frozen and shared with
`cloud/gateway/enforcement.py`.

## Phase 3 — luna-service consumes the new dimensions

`cloud/gateway/enforcement.py`:

- Ingest `x-luna-job-id` → `BillableEvent.job_id` (currently never set) so
  per-trigger / per-playbook grouping is stable even when `root_action_id`
  is NULL on headless turns. Keep the existing `channel` + allow-listed
  `root_action_type` ingest.

`cloud/api/billing_routes.py` `usage_channels`:

- Rework the `bucket` `case` into the **precedence** classification above
  (scheduler → playbook_run → whatsapp → telegram → web).
- Add a **Playbooks** section (`root_action_type = playbook_run` AND not
  scheduler) with a per-playbook breakdown (key = `job_id` → playbook id →
  `root_action_id`), mirroring the scheduler per-trigger split.
- Per-item `name`: resolve trigger/playbook ids to human names where a
  source exists (scheduler admin proxy for triggers; playbook manifest for
  playbooks); fall back to the id.

`cloud/ui/src/pages/billing/*`:

- Add the **Playbooks** `ChannelCard` + expandable per-playbook list
  (reuse `SchedulerTriggers` pattern). New `api.ts` types include a
  `playbooks` section.

## Phase 4 — Tests (devprocess)

- Unit (`cloud/tests/test_billing_customer_api.py`): extend the channel
  seed with scheduler + playbook_run rows (with `job_id`); assert the
  precedence buckets, non-overlapping totals, per-trigger + per-playbook
  splits, and `y_max = max(peak, 200)` (including the floor when all days
  < 200).
- Gateway (`test_gateway.py`/enforcement): `x-luna-job-id` ingested into
  `job_id`; corrected `root_action_type` values accepted.
- Dojo (`tests/048-action-origin-tracking/`): seed scheduler + playbook +
  web + wa/tg data; verify the 5 sections, precedence (a scheduled
  playbook shows under Scheduled not Playbooks), per-item expand, the
  removed range filter, smaller/gridline-free/square/half-width bars, and
  the shared 200-floor y-scale. Browser-run with screenshots.
- Luna side: extend
  `luna/tests/039-luna-metering/phase01/test_context_transport.py` to
  assert `x-luna-channel`, `x-luna-job-id`, and corrected
  `x-luna-root-action-type` for web/scheduler/playbook entry points.

## Rollout / degradation

- Phase 1 ships alone and is immediately visible.
- Phases 2–3 need coordinated releases: luna core, plugin-scheduler,
  plugin_playbooks, then luna-service. Until all land, scheduler/playbook
  sections are empty and traffic folds into Chat (no breakage).
- `job_id` column is already present and nullable; no migration needed.
  Ingesting it is additive.

## Decisions / open questions

- **Playbooks vs Scheduled precedence:** scheduler wins (a scheduled
  playbook counts as Scheduled). Rationale: the user thinks of the daily
  trigger as the cost driver, not the playbook it happens to invoke.
  Revisit if they'd rather see playbook spend regardless of trigger.
- **Trigger/playbook names:** best-effort resolution; ship ids first if no
  clean name source, improve later (same stance as 046).
- **`api` channel:** folds into Chat for now (no separate section) unless
  the user wants it surfaced.
