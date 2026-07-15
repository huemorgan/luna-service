# 040 — Cost Testing (agent token/credit benchmark)

## Vision

Answer, with measured numbers instead of guesses: **what does a user action cost?**
"Say hello" → a reply: how many credits, how many vendor micro-USD, what margin?
Same for every deeper thing users actually do — web search, file summarization,
image generation, a scheduled task firing, a day of idle background burn.

Deliverable is a new admin page — **Billing testing** in the left pane (pricing
group) — that:

1. takes a live agent instance and drives it through a **test playbook** of
   typical user actions (chat messages, plugin-triggering prompts, API calls);
2. measures **cost per item**: credits charged, vendor cost in $, margin,
   tokens in/out per model, latency;
3. composes items into **usage profiles** ("regular user") and projects
   **monthly cost per agent** for that pattern (metering + hosting);
4. records a **full detailed trigger log** of everything that fired during a
   run — every gateway request, model, token counts, cache hits, cost — so we
   can later open a run and know exactly what happened when we optimize.

Everything here is admin-only. Pricing internals (vendor cost, margins,
micro-USD) stay invisible to customers and to the Luna agent itself — the
benchmark drives the agent from the outside exactly like a user would.

## What exists already (reuse, don't rebuild)

- **Metering is complete** (plan 039): every LLM call through the gateway lands
  in `billable_events` (vendor_cost_micro_usd, tokens, model, service) and is
  rated into `rated_charges` (credits, vendor_cost, margin, rounding,
  luna_absorbed) with ledger postings per account.
- **Simulator** (039/009, `/admin/pricing/simulations`): synthetic what-if runs
  against pricing versions. The benchmark is its live-fire sibling: real agent,
  real vendor calls, real rated charges. Reuse its result-table UI idioms.
- **Driving an agent from outside is proven** (Rayla canary, 2026-07-15): proxy
  `POST /a/{slug}/api/auth/proxy-login` → Bearer token → create conversation →
  `POST /api/conversations/{id}/messages` (SSE reply). The done-event even
  returns context-token breakdowns we can log.
- **Local runtime exists**: `cloud/runtime/docker_local.py` runs a real Luna
  image locally; the 039 dojo pattern (scratch PG on :5435, cloud on :810x)
  gives us an isolated local bench.
- **Attribution keys exist**: `billable_events.agent_id` + timestamps; per-run
  attribution = agent_id + time-window + (new) benchmark run marker.

## Design

### Data model (new tables, `cloud/billing/models.py`)

- `benchmark_runs` — id, target agent_id/account_id, image version, model chain,
  pricing version in effect, playbook version, profile (nullable), status
  (running/completed/aborted), started/finished, totals (credits, vendor
  micro-USD, margin, tokens, requests), created_by, notes.
- `benchmark_steps` — run_id, item_key (from the playbook catalog), seq,
  started/finished, status, latency_ms, and measured aggregates: llm_requests,
  input_tokens, output_tokens, cache_read/write tokens per model (JSON),
  credits, vendor_cost_micro_usd, margin_micro_usd, non-LLM service calls
  (composio/openai-images/…) with their costs.
- `benchmark_step_events` — the **detailed trigger log** (Roy's requirement):
  one row per billable/observable event inside a step, ordered: ts,
  billable_event_id (FK when rated), service, model, endpoint, tokens in/out,
  cache tokens, vendor micro-USD, credits, http status, latency. Plus
  run-scoped noise capture: events on the target agent during the run that
  belong to *no* step (background burn) attach to a synthetic `__background__`
  step so nothing that fired goes unrecorded.
- Content rule unchanged: **no prompts, no outputs, no tool arguments** in any
  billing/benchmark table. Steps reference the playbook item key; the item's
  prompt text lives in the versioned catalog in code, so a run is still fully
  reproducible without storing conversation content.

### Runner (`cloud/billing/benchmark.py` + worker job)

- Admin picks a target agent (must be a **designated test agent**, guarded — the
  runner refuses agents not flagged `is_benchmark_target` to avoid polluting a
  real user's conversations and wallet).
- For each playbook item: mark step start → execute the action (chat message
  via proxy path, direct Luna API call, or trigger definition) → wait for the
  SSE done event / poll completion → settle window (few seconds for async
  rating) → collect every `billable_event`/`rated_charge` for that agent in the
  step window → write step + step_events.
- Isolation between items: fresh conversation per item unless the item is
  explicitly multi-turn; optional pre-step "drain" wait so background activity
  doesn't bleed into the item's window (and is captured as `__background__`).
- Repetitions: each item runs N times (default 3) → report median and spread;
  token costs vary run to run.
- Runs execute as a `billing_jobs` job (existing worker) so the API returns
  immediately and the UI polls progress.

### Playbook catalog (`cloud/billing/benchmark_playbook.py`, versioned)

Fixed prompts, one key per item. Categories, with the plugin each exercises:

**Baseline chat**
- `chat.hello` — "say hello", one-line reply (the canary measured ~22 cr).
- `chat.qa_short` — factual question, paragraph answer.
- `chat.generate_long` — long-form writing (~800 words out).
- `chat.multiturn_5` — 5-turn conversation (context growth cost).
- `chat.big_context` — question against a long seeded history (cache economics).

**Core plugins (in-tree: plugin_api, plugin_webui, plugin_brain, plugin_memory,
plugin_identity, plugin_tasks, plugin_approvals, plugin_vault, plugin_config,
plugin_meta, plugin_marketplace, plugin_onboarding, plugin_upgrade_awareness,
plugin_dojo_bridge, plugin_dojo_socialkit, plugin_mock_tool)**
- `memory.store` / `memory.recall` — tell the agent a fact; later ask for it
  (plugin_memory + plugin_brain auto-extract — extraction is a hidden LLM cost
  per message, must be visible as its own trigger-log rows).
- `tasks.create_and_run` — ask for a task, let it execute (plugin_tasks).
- `approvals.roundtrip` — action that requires approval, approve it
  (plugin_approvals).
- `meta.introspect` — "what plugins do you have?" (plugin_meta, cheap control).
- `onboarding.full` — one-time onboarding conversation cost (fresh agent only).
- `background.idle_24h` — **no user input at all**: measure a day of idle burn
  (brain ticks, dojo_socialkit, upgrade_awareness checks, heartbeats). Run as a
  window-only measurement, scaled from a shorter sample (e.g. 2h × 12).
- plugin_api / plugin_webui / plugin_identity / plugin_vault / plugin_config /
  plugin_marketplace / plugin_dojo_bridge have no per-use LLM cost of their own
  — covered implicitly by every item; noted in the catalog as zero-cost paths
  so the coverage table shows all plugins accounted for.
- plugin_mock_tool — used in the local bench to exercise the tool-call loop
  without external spend (`tool.mock_roundtrip`).

**Marketplace plugins (current default image set — all 14)**
- `recall.search` — plugin-recall query.
- `mcp.tool_call` — plugin-mcp tool invocation against a local MCP fixture.
- `charts.render` — "chart this data" (plugin-charts).
- `web.search_summarize` — "look up X and summarize" (plugin-web-access).
- `connectors.action` — a composio action, e.g. read inbox count
  (plugin-connectors; composio requests are billable non-LLM events).
- `files.summarize_doc` — upload a fixture doc, ask for a summary (plugin-files).
- `browser.session` — "open this page and extract the table" (plugin-browser).
- `htmlpage.generate` — "make me a page" (plugin-html-page).
- `imagegen.one` — one image (plugin-image-gen; openai image cost).
- `playbooks.run` — run a stored playbook (plugin-playbooks).
- `giphy.send` — "send a gif" (plugin-giphy).
- `curiosity.tick` — one curiosity cycle (plugin-curiosity; background cost).
- `wiki.write` — "add this to your wiki" (plugin-wiki).
- `scheduler.task_fire` — create a scheduled task, measure one firing
  (plugin-scheduler; recurring cost = per-fire × frequency).

**API usage**
- `api.direct` — scripted Luna API calls (conversations list, messages fetch,
  events stream) — proves reads are free, writes cost only what the agent does.

### Usage profiles → monthly projection

- A profile = list of (item_key, frequency per month). Presets seeded:
  - **Light**: 30× hello-class chats, 10× qa_short, background idle × 30 days.
  - **Regular**: 60× chat mix, 20× web.search, 8× files/charts, 4× imagegen,
    1 daily scheduler task (30 fires), memory on every message, idle × 30.
  - **Heavy**: 10× regular's volumes on the deep items, browser sessions, MCP.
- Projection = Σ (median item credits × freq) + background.idle × 30
  + hosting (999 cr/month) → shown as credits, vendor $, revenue $ (credits ×
  $0.01), and margin. Profiles are editable in the UI (frequency spinners) and
  recompute live from the latest completed run's medians.

### Admin UI — left-pane "Billing testing"

Route `/admin/pricing/testing`, nav item in the pricing group (icon: Gauge),
page `cloud/ui/src/pages/admin/pricing/BillingTestingPage.tsx`:

- **Run panel**: target agent picker (benchmark-flagged agents only), playbook
  item multi-select (default all), repetitions, model override, Run button,
  live progress (step k/n, running totals).
- **Results table**: one row per item — median credits, vendor $, margin %,
  tokens in/out, LLM requests, latency; spread across repetitions; compare
  column vs a previous run (cost regressions become visible).
- **Trigger log drill-down**: expand any step → the ordered
  `benchmark_step_events` list (ts, service, model, endpoint, tokens, cache,
  micro-USD, credits, status, latency), plus the `__background__` bucket.
  **Export run as JSON/CSV** for offline optimization analysis.
- **Profiles tab**: preset + custom profiles, monthly projection cards
  (credits / vendor $ / revenue / margin), per-item contribution breakdown so
  the expensive line items pop.
- **History tab**: past runs with image version, model chain, pricing version —
  the longitudinal record ("did 0.37 get cheaper?").

### API (`cloud/api/billing_admin_routes.py`, admin-only)

- `POST /api/admin/pricing/benchmark/runs` (start), `GET /runs`, `GET
  /runs/{id}` (steps + totals), `GET /runs/{id}/events` (trigger log, paged),
  `GET /runs/{id}/export`, `POST /runs/{id}/abort`,
  `GET/PUT /api/admin/pricing/benchmark/profiles`.

## Local testing plan

The point of this plan: everything above runs **locally first**.

1. **Bench environment** (mirrors 039 dojo): scratch PG `dojo040bench` on
   :5435, cloud app on :8106, gateway pointed at real providers with a
   dev Anthropic key. Target agent = real Luna image via `docker_local`
   runtime, provisioned with `ANTHROPIC_BASE_URL` → local gateway + tenant
   token, account put in `enforce` via the per-account override (039), seeded
   with a 5 000-credit gift.
2. **Real spend, capped**: local runs hit real vendors (that's what makes the
   $ numbers true). Guardrails: cheap default model for smoke runs, per-agent
   `AgentCreditLimit` on the bench agent, playbook smoke subset (~10 items)
   for iteration, full catalog only on explicit `--full`.
3. **Deterministic tests without spend**: unit tests mock the provider layer
   (fixed token counts) and assert attribution, step windows, background
   bucketing, profile math, export shape. `plugin_mock_tool` covers the
   tool-loop path free.
4. **Dojo script** `tests/040-cost-testing/dojo_cost_benchmark.py`: boots the
   bench env, runs the smoke subset against the local agent, asserts every step
   has ≥1 trigger-log row, credits > 0 on LLM items, ledger delta == Σ step
   credits (+background), export validates, invariants hold. Results under
   `tests/040-cost-testing/results/`.
5. **Idle-burn sample**: dojo variant that leaves the local agent alone for a
   bounded window and verifies background events land in `__background__` and
   scale into the profile math.
6. Only after local dojo is green: run once against a prod **test** agent
   (never a real user's) to calibrate real-image numbers.

## Phases

- **001 schema & runner** — tables + migration, benchmark.py runner with step
  windows, attribution, background bucket, worker job, abort. Unit tests.
- **002 playbook catalog** — all items above incl. every core + marketplace
  plugin; per-item execution adapters (chat / API / scheduled / window-only);
  coverage table asserting all plugins in the current default set appear.
- **003 admin API + UI** — routes, left-pane entry, run panel, results, trigger
  log drill-down, export. UI build green.
- **004 profiles & projection** — presets, custom profiles, monthly math with
  hosting, comparison vs previous run.
- **005 local dojo & calibration** — bench env, smoke + full runs, idle-burn
  sample, execution summary with the first real cost table.

## Non-goals / guards

- Never runs against non-flagged agents; never exposed outside /admin.
- No prompts/outputs/tool-args stored in billing or benchmark tables.
- Vendor cost, margin, micro-USD stay admin-only (existing 039 rule).
- Benchmark spend is real money — bench account is gift-funded and
  credit-limited; runs abort when the bench wallet empties (enforcement 402s
  are themselves a useful test of the block path).
