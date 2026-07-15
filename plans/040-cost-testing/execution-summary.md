# 040 — Cost testing: execution summary

Executed 2026-07-15. All phases delivered in one pass; full regression green
(622 passed, 1 skipped), 19 new unit tests, 11-scenario live dojo on real
Postgres.

## What was built

**Schema (migration 0008)** — three tables:
- `benchmark_runs` — one row per benchmark: agent, item keys, repetitions,
  state machine (pending → running → succeeded/failed/aborted), progress,
  totals JSONB.
- `benchmark_steps` — one row per (item × repetition) plus a synthetic
  `__background__` step per run: latency, LLM requests, token counts
  (in/out/cache read/cache write), per-model breakdown, credits, vendor
  micro-USD, margin.
- `benchmark_step_events` — the full trigger log: one row per billable event
  observed in the step's time window, with verbatim `quantities`, vendor cost,
  and the call's credits pinned to its final attempt row (summing never
  double-counts). This is the optimization log the plan required — after a
  run you can see exactly what fired, when, on which model, and what it cost.
  No prompts, outputs, or tool arguments are ever stored.

**Runner** (`cloud/billing/benchmark.py`) — a durable-worker job
(`cost_benchmark`, max_attempts=1). `HttpAgentDriver` drives the target agent
exactly like the cloud proxy does (derived per-agent proxy secret,
proxy-login → bearer, SSE message stream). Attribution is time-window based
with claimed-event and claimed-call sets so calls straddling windows charge
once; everything outside every step window lands in `__background__`.
Guard: refuses agents not flagged `config_overrides.benchmark.target` — a run
pollutes conversations and spends the wallet for real. Abort is read across
transactions between steps; per-step commits keep partial results.

**Playbook** (`benchmark_playbook.py`, v1) — ~26 versioned items across chat,
memory, recall, wiki, tasks, scheduler, approvals, playbooks, web, browser,
curiosity, files, charts, html-page, image-gen, giphy, MCP, connectors, meta,
onboarding, direct API reads, and a background-idle window. Coverage is a
provable contract: `uncovered_plugins() == []` over all 16 core + 14
marketplace plugins is asserted in unit tests, the dojo, and surfaced in the
UI; zero-cost plugins are annotated with reasons.

**Profiles** (`benchmark_profiles.py`) — light/regular/heavy presets mapping
item keys to monthly frequencies. Projection prices a profile from a run's
measured medians: metered credits + background idle scaled to 24 h × days +
hosting (999 cr default) → monthly credits, revenue, vendor $, margin.

**Admin API** — 10 endpoints under `/api/admin/pricing/benchmark/*`:
playbook, targets list/flag (audited, reason required), run start
(audited)/list/detail/events/export/abort, projection. Export returns the
whole run with the nested trigger log as one JSON document.

**UI** — `/admin/pricing/testing` ("Billing testing" in the pricing group,
Gauge icon): target flagging, run form (smoke/default/custom item chips per
category), live-polling run table with progress, step table with per-step
trigger-log viewer, JSON export link, and a projection panel.

## Verification

- `cloud/tests/test_billing_benchmark.py` — 19 tests: coverage contract,
  catalog shape, start guard, attribution (tokens, per-model, final-attempt
  credits, background bucket), failure isolation, abort, median/projection
  math, and the admin API (auth, CSRF, reasons, audit, lifecycle, 400s).
- `tests/040-cost-testing/dojo_cost_benchmark.py` — live end-to-end on
  scratch Postgres :5435: mock Luna agent calling back through the REAL
  gateway + enforcement in enforce mode. Proven: worker executes the run,
  steps carry real rated credits (2×chat.hello = 8 credits), trigger log
  links billable events with verbatim quantities, the wallet actually drained
  500 → 492, driver auth (derived proxy secret + creator email + bearer),
  projection priced from medians, abort stopped 1/10 steps, audit rows for
  flag/start/abort.

## Notes for production use

- Flag a dedicated test agent (e.g. Rayla) via the UI, run the smoke set
  first; runs spend the target account's wallet for real under enforce.
- `api.direct` measures read-only API traffic and correctly costs 0.
- Items marked default-off (approvals, MCP, connectors, onboarding, mock
  tool) need environment-specific setup; enable per run.
