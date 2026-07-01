# 023 — External Scheduler (the clock lives on us, the work lives in Luna)

> Hosted Lunas run on **ephemeral** Fly machines (scale-to-zero / sleep). An
> ephemeral machine **cannot** be trusted to keep its own cron. So for the hosted
> product the *clock* moves to the control plane (Render, always-on): we tick, we
> **wake** the tenant machine, and we **trigger** a Luna plugin that does the
> actual work. The OSS Luna — running 24/7 on a real box — keeps its clock local
> and just uses cron.
>
> This plan has two parts:
> 1. **Our side** (`luna-service`): the always-on External Scheduler service.
>    This is what we build and execute here.
> 2. **What we need from Luna** (the `external-scheduler` plugin contract we
>    depend on). We do **not** build this — it's a proposal for Luna's team,
>    written up at `plans/luna-proposals/023-external-scheduler-plugin.md`. The
>    `luna/` submodule is never touched from this repo. Part 2 below is a short
>    summary of that contract so this plan is self-contained.

## Why this isn't (only) a Luna problem

Luna's own scheduler plan (`luna/plans/008-changes/008.009-scheduler-plugin`)
designs an **in-process** cron tick loop: a task inside the agent polls
`next_run_at <= now()` and fires. That is correct **for a process that is always
running** — i.e. self-hosted OSS Luna on a 24/7 machine. It is wrong for us:

- Our tenant machines **stop** when idle (cost + the whole hosted model). A
  stopped machine has no tick loop, so a self-contained scheduler simply doesn't
  fire while the user is away — which is exactly when scheduled work matters
  ("email me a summary at 9am").
- Only the **control plane** is guaranteed always-on. It already knows how to
  **wake** a stopped machine (`cloud/api/proxy.py::_try_wake_agent`) and how to
  deliver a **signed** event to a plugin ingress with auto-wake + retry
  (`cloud/relay/forwarder.py`, shipped for Composio in plan 015).

So: **the external scheduler is the Composio-relay pattern pointed at a clock
instead of a webhook.** Same outbox, same signing, same wake, same plugin
ingress shape — the trigger source is `cron` instead of `Composio`.

## The shape (hosted)

```
            ┌─────────────────────── control plane (Render, always-on) ───────────────────────┐
            │  external_schedules (when + what)                                                │
 agent tool │  ticker.py  ── due? ──▶ enqueue fire ──▶ relay outbox ──▶ forwarder              │
 register ─▶│      ▲                                                      │ sign + wake + POST  │
 (machine   │      │ register/list/delete (gateway-token auth)           ▼                      │
  → us)     └──────┼──────────────────────────────────────────  /api/p/external-scheduler/fire ┘
                   │                                                      │
        ┌──────────┴───────────── tenant Luna machine (Fly, ephemeral) ──┴──────────┐
        │  plugin_external_scheduler                                                  │
        │   • tools: schedule_create/list/delete/pause/resume/run_now (agent + PB)    │
        │   • /fire ingress (Standard-Webhooks verified, idempotent on fire_id)       │
        │   • on fire → emit the SAME internal contracts as OSS 008.009:              │
        │       playbook  → playbook.run.requested {name,inputs}  → real run          │
        │       agent     → message.received {channel:"scheduler", text}  → agent loop │
        └─────────────────────────────────────────────────────────────────────────── ┘
```

The fire path **inside** Luna is identical to OSS 008.009. Only *who owns the
clock* differs. That symmetry is the whole design: one plugin, two clocks.

## Decisions

- **D0 — In-house ticker on Render; no external cron vendor.** We evaluated
  offloading the clock to a managed service. Native crons (Render Cron Jobs,
  Cloudflare Cron Triggers, Fly scheduled machines) are **static** — defined at
  deploy time in `render.yaml` / `wrangler.toml` — so they can't express
  per-tenant schedules created at runtime; disqualified. Dynamic schedule
  vendors (Upstash QStash, Posthook, AWS EventBridge Scheduler, GCP Cloud
  Scheduler) fit the "create a schedule via API" shape **but can't wake a
  sleeping Fly machine** — they only POST to a URL — so we'd keep our forwarder
  (wake + per-agent signing + retry + dead-letter) regardless. They'd replace
  only the trivial ~50-line poll loop while adding a vendor secret, a failure
  mode, and a second schedule store to keep in sync with `external_schedules`.
  Since the hard machinery already exists (Composio relay, plan 015), building
  the ticker ourselves is **less** total complexity. (Escape hatch if we ever
  want zero self-run clock: Upstash QStash — API-created cron schedules,
  JWT/HMAC-signed delivery, built-in retries — pointed at a control-plane `/tick`
  endpoint that then wakes+forwards. Only a clear win if Fly auto-start-on-request
  proves reliable enough to also drop the forwarder, which our explicit-wake relay
  suggests it isn't. Not chosen.)

- **D1 — One plugin, two clock modes (`SCHEDULER_MODE = external | local`).**
  We ask Luna for a single `external-scheduler` plugin. In `external` mode
  (hosted) it has **no local tick loop**; it waits for our `/fire` calls and its
  tools **register schedules with the control plane**. In `local` mode (OSS /
  24/7) it runs its own `croniter` tick that calls its own `/fire` (or emits
  directly) — that local tick is effectively 008.009. Hosted sets
  `SCHEDULER_MODE=external` via provisioning env; OSS defaults to `local`.

- **D2 — Source of truth for "when" is the control plane (hosted).** Because the
  machine is ephemeral, the durable schedule store that the *clock* reads lives
  on Render (`external_schedules`). The plugin keeps a thin display mirror for
  its Settings UI and `schedule_list`, but the control-plane row is what fires.
  (OSS `local` mode: the plugin's own DB is the source of truth — no control
  plane involved.)

- **D3 — The scheduler emits events; it never runs work in-process.** Exactly
  008.009's rule. `/fire` only emits `playbook.run.requested` or a synthetic
  `message.received`. So a scheduled playbook is a normal run — it gets the
  running indicator (008.006) and Stop (008.007) for free, and the scheduler
  imports no other plugin.

- **D4 — Reuse the relay outbox + forwarder, don't build a new delivery path.**
  Generalize `cloud/relay/forwarder.py` (today hardcodes
  `EVENTS_PATH=/api/p/plugin-connectors/events/composio`) to deliver to a
  per-row target path, and add a fire payload. We get signing, per-agent secret
  derivation, **auto-wake**, exponential backoff, and dead-lettering unchanged.

- **D5 — Registration auth = the agent's existing gateway token.** The
  machine→control-plane direction is already authenticated for the LLM gateway
  (`gateway_proxy.py` → `token_svc.verify_token(db, credential) -> agent_id`).
  The plugin's register/list/delete calls present the **same** token; the control
  plane resolves `agent_id` and scopes the schedule to that agent. No new secret
  to provision for the inbound direction.

- **D6 — Fire delivery is signed + idempotent.** Standard Webhooks signature with
  the per-agent derived secret (`derive_relay_secret`, same as Composio), plus a
  `fire_id` the plugin dedupes on, so a forwarder retry can't double-run a
  playbook.

- **D7 — Parsing lives where the clock lives.** The control plane parses cron/NL
  and computes `next_run_at` (mirror 008.009 D5: `croniter` + a tiny explicit NL
  phrase list, no LLM). In `local` mode the plugin parses. Same expression
  grammar both sides so a schedule reads identically.

- **D8 — Overdue fires once; tight schedules are the operator's brake.**
  Advisory-locked ticker, overdue > one interval fires **once** (no catch-up
  storms), `min_interval_seconds` floor, pause/disable as the kill switch. Same
  posture as 008.009 + the relay's existing backoff/dead-letter.

## Part 1 — Our side (`luna-service`)

### Phase A — schema + expression engine
- `cloud/db/models.py`: `external_schedules` (`id`, `agent_id` FK, `name`,
  `expr_raw`, `expr_cron`, `timezone`, `action_type` `'agent_prompt'|'playbook'`,
  `target` (prompt text or playbook name), `inputs` jsonb, `enabled`,
  `min_interval_s`, `next_run_at`, `last_run_at`, `created_by`, `created_at`).
  Fire history reuses `relay_deliveries` rows tagged `kind='schedule_fire'` for
  the outbox + an admin view (Q4 confirmed — one outbox, no dedicated table).
- `cloud/scheduler/expr.py`: `parse(raw, tz) -> cron`, `next_run(cron, tz, after)`
  (`croniter`), explicit NL phrases, `InvalidScheduleExpr`. (Lifted from 008.009.)

### Phase B — the always-on ticker
- `cloud/scheduler/ticker.py`: asyncio task started in `main.py` lifespan
  (skipped under tests), polls every ~15s:
  `SELECT id FROM external_schedules WHERE enabled AND next_run_at <= now()`,
  Postgres **advisory lock** per `schedule_id` (HA-safe across >1 Render
  instance), then **enqueue a fire** into the relay outbox and recompute
  `next_run_at`. Overdue fires once.

### Phase C — fire delivery (generalize the relay forwarder)
- Add a `target_path` (+ optional `kind`) to the delivery row; forwarder POSTs to
  `{internal_url}{target_path}` instead of the hardcoded composio path.
- Fire body: `{ fire_id, schedule_id, action_type, target, inputs, fired_at }`,
  signed with `derive_relay_secret(root, agent_id)`; `x-luna-proxy-secret` +
  `fly-force-instance-id` as today; auto-wake + backoff + dead-letter inherited.
- Target path: `/api/p/external-scheduler/fire`.

### Phase D — registration API (machine → control plane)
- `cloud/api/scheduler_routes.py`, authenticated by the agent gateway token
  (reuse `token_svc.verify_token`):
  - `POST /api/scheduler/schedules` — create/upsert (parses expr, computes
    `next_run_at`, scopes to resolved `agent_id`). Returns `{id, expr_cron,
    next_run_at}`.
  - `GET /api/scheduler/schedules` — list for the agent (for the plugin mirror).
  - `DELETE /api/scheduler/schedules/{id}` · `POST .../{id}/pause|resume|run-now`.
- `run-now` just enqueues a fire immediately (work still gated downstream).

### Phase E — provisioning + env
- `cloud/provisioning/workflow.py` `_provision_core`: inject into the machine
  `SCHEDULER_MODE=external`, `LUNA_CONTROL_PLANE_URL` (our base), and ensure the
  agent already has its gateway token in env (it does, for the LLM gateway) so
  registration can authenticate. Add `LUNA_EXTERNAL_SCHEDULER_SECRET` (derived
  per-agent) for `/fire` verification — same mechanism as the composio secret.
- `.env.example`: document any new `CLOUD_*` (none required beyond the existing
  `CLOUD_TRUSTED_PROXY_SECRET` root; note the scheduler reuses it).

### Phase F — admin visibility
- Extend the existing Relay/admin area: a "Schedules" table (agent, name, expr,
  next/last run, enabled) + a fires table (status, attempts) reusing the relay
  delivery view. Table-only, matches `RelayPage` style.

### Phase G — tests (`tests/023-external-scheduler/` + `cloud/tests/`)
- Unit: expr parsing/DST; ticker due-selection + advisory-lock single-fire;
  fire enqueue + signature; registration token-auth scoping; idempotent fire.
- Dojo (the real proof): a **hosted** Luna, machine allowed to **stop** →
  schedule "every 2 minutes → playbook X" created via the agent tool → control
  plane registers it → at fire time the machine is **woken** and X runs (running
  badge + Stop) → pause stops firing → delete removes it. Agent-prompt schedule
  likewise wakes + posts a chat turn.

## Part 2 — What we need from Luna (the dependency we're based on)

We do **not** build this. It's a proposal for Luna's team, written in full at
`plans/luna-proposals/023-external-scheduler-plugin.md` (the `luna/` submodule is
never touched from this repo). Framed as deltas on the existing 008.009 design —
**most internals already exist**; we need the *external-clock* surface. Summary:

**Plugin: `plugin_external_scheduler` (type `system`, MIT).**

1. **Tools (agent- and playbook-callable)** — the user's core ask:
   `schedule_create(name, schedule_expr, action_type, target, inputs?, timezone?)`,
   `schedule_list`, `schedule_delete`, `schedule_pause`, `schedule_resume`,
   `schedule_run_now`. In `external` mode these proxy CRUD to our
   `/api/scheduler/schedules` (auth: the agent's gateway token) and cache a local
   mirror; in `local` mode they write the plugin's own DB + drive a local tick.

2. **Fire ingress** `POST /api/p/external-scheduler/fire` — Standard-Webhooks
   verified against `LUNA_EXTERNAL_SCHEDULER_SECRET`, **idempotent on `fire_id`**.
   On valid fire, emit the internal contract by `action_type`:
   - `playbook` → `playbook.run.requested {name, inputs, source:"external-scheduler"}`
   - `agent_prompt` → `message.received {channel:"scheduler", sender:"luna-scheduler", text}`

3. **The generic `playbook.run.requested` contract + the one-line
   `plugin_playbooks` subscription** (008.009 Phase C / D3). This is the bridge
   that turns a fire into a real run. If 008.009 ships it, we just consume it; if
   not, it's a hard dependency for us.

4. **Mode flag** `SCHEDULER_MODE = external | local` (env), defaulting to `local`
   for OSS. In `external` mode: **no local tick loop** (the control plane owns
   the clock) and tools register upstream.

5. **Settings/Schedules UI** (plugin-owned) — reuse 008.009 Phase E; in
   `external` mode it reads the mirror / our list endpoint.

**Relationship to 008.009:** ideally **fold both clocks into this one plugin**
(rename `plugin_scheduler` → `plugin_external_scheduler`, add `mode` + `/fire`),
so OSS and hosted share code and only the clock differs. If the Luna roadmap
prefers to keep `plugin_scheduler` as the local-only one, then what we strictly
need is the **`/fire` ingress + upstream-register hook + `playbook.run.requested`
contract** added so an external clock can drive it. Either is fine for us; the
contract above is what we build against.

## Non-goals
- No new workflow concept; multi-step scheduled work = a **playbook** we target.
- No exactly-once semantics beyond advisory-lock dedup + `fire_id` idempotency
  (a missed window fires once on recovery, not N times).
- No changes to playbook step execution / approvals / run model.
- No OSS cron work owned here — `local` mode is Luna's 008.009.

## Risks
- **Machine won't wake at fire time** → forwarder backoff + dead-letter (exists);
  a fire that can't be delivered in the retry window is dropped with a recorded
  failure, not retried forever.
- **Double-fire across control-plane instances** → advisory lock per
  `schedule_id` (ticker) **and** `fire_id` idempotency at the plugin (delivery).
- **Catch-up storms after our downtime** → overdue fires once.
- **Runaway tight schedule** (our 2.4M-token incident, on a clock) →
  `min_interval_seconds` + pause/disable + 008.007 cancel on the resulting run.
- **Registration spoofing** → gateway-token auth scopes every write to the
  resolved `agent_id`; a machine can only touch its own schedules.
- **Fire spoofing** → Standard-Webhooks signature with the per-agent secret.
- **Timezone/DST** → store tz; compute `next_run` on the clock-owning side; test
  across DST + month-end.

## Acceptance criteria
- [ ] A hosted Luna whose machine is **stopped** still fires on time: control
      plane wakes it and the playbook runs (indicator + Stop visible).
- [ ] Schedules created by the agent via a plugin tool appear in
      `external_schedules` and fire; pause/delete take effect.
- [ ] `/fire` is signature-verified and idempotent (replayed `fire_id` = no
      second run).
- [ ] Registration is gateway-token-scoped (agent A cannot create/read agent B's
      schedules).
- [ ] Ticker is advisory-locked (two control-plane instances → single fire);
      overdue fires once; `min_interval_seconds` enforced.
- [ ] OSS `local` mode still works with no control plane (the plugin's own tick).
- [ ] Unit tests green; dojo scenario passes against the local stack with a
      machine that is allowed to sleep between fires.

## Resolved decisions (previously open questions)
- **Q1 — Merge or sibling?** **Luna's team's call** (it's their plugin). Our
  recommendation in the proposal: fold 008.009 `plugin_scheduler` into
  `plugin_external_scheduler` (one plugin, `mode` flag). Not a blocker for us —
  we build against the contract either way.
- **Q2 — Schedule store of record (hosted): CONFIRMED** — control-plane
  `external_schedules` is the firing source of truth, plugin keeps a mirror (D2).
- **Q3 — Registration auth: CONFIRMED** — reuse the agent **gateway token**, zero
  new provisioning (D5).
- **Q4 — Fire history: CONFIRMED** — reuse `relay_deliveries` tagged
  `kind='schedule_fire'` (one outbox), not a dedicated table (Phase A / C).
