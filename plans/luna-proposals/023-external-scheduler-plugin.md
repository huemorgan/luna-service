# Proposal for Luna — `plugin_external_scheduler` (one plugin, two clocks)

> This is a PROPOSAL written in the luna-service repo. It is NOT a Luna plan
> yet, and nothing in `luna/` is touched from here. If accepted, Luna's team
> recreates it inside the Luna project (suggested as a revision/extension of
> `008.009-scheduler-plugin`) and executes it via Luna's own process.
>
> The control-plane side that depends on this contract is
> `plans/023-external-scheduler/PLAN.md` in luna-service.

## The ask in one line

A scheduler plugin that works in **two clock modes**:

- **`local`** (OSS / 24/7 box): runs its own `croniter` tick — this is exactly
  the existing `008.009-scheduler-plugin` design.
- **`external`** (hosted / ephemeral Fly machine): **no local tick loop**. The
  control plane (luna-service on Render, always-on) owns the clock, and on each
  due schedule it POSTs a signed **fire** to a plugin ingress. The plugin's
  scheduling tools register schedules **upstream** with the control plane.

The fire path *inside* Luna is identical in both modes — only *who owns the
clock* differs. That symmetry is the whole point: one plugin, two clocks.

## Why hosted can't use the 008.009 in-process tick

008.009 polls `next_run_at <= now()` from inside the agent process. That is
correct for a process that is always running. Hosted tenant machines **stop when
idle** (cost + the hosted model), so a stopped machine has no tick loop and a
self-contained scheduler simply doesn't fire while the user is away — which is
exactly when "email me a summary at 9am" matters. Only the control plane is
guaranteed always-on, and it already knows how to **wake** a stopped machine and
deliver a **signed** event with auto-wake + retry (the Composio relay pattern,
plan 015). So for hosted, the external scheduler is "the Composio relay pointed
at a clock instead of a webhook."

## What we need from the plugin (contract we build against)

**Plugin: `plugin_external_scheduler` (type `system`, MIT).**

1. **Tools (agent- and playbook-callable)** — the user's core ask:
   `schedule_create(name, schedule_expr, action_type, target, inputs?, timezone?)`,
   `schedule_list`, `schedule_delete`, `schedule_pause`, `schedule_resume`,
   `schedule_run_now`.
   - In `external` mode these proxy CRUD to the control plane
     (`POST/GET/DELETE /api/scheduler/schedules` + `…/{id}/pause|resume|run-now`),
     authenticated with **the agent's existing gateway token** (the same token
     the machine already uses for the LLM gateway — no new secret to provision).
     They keep a thin **local mirror** for the Settings UI / `schedule_list`, but
     the control-plane row is what fires.
   - In `local` mode they write the plugin's own DB and drive a local tick.

2. **Fire ingress** `POST /api/p/external-scheduler/fire` — verified with
   Standard Webhooks against `LUNA_EXTERNAL_SCHEDULER_SECRET` (per-agent derived,
   same mechanism as the Composio secret), **idempotent on `fire_id`** so a
   forwarder retry can't double-run. On a valid fire, emit the internal contract
   by `action_type`:
   - `playbook` → `playbook.run.requested {name, inputs, source:"external-scheduler", fire_id}`
   - `agent_prompt` → `message.received {channel:"scheduler", sender:"luna-scheduler", text}`

   Fire body we will POST:
   ```json
   { "fire_id": "...", "schedule_id": "...", "action_type": "playbook|agent_prompt",
     "target": "...", "inputs": {}, "fired_at": "..." }
   ```

3. **The generic `playbook.run.requested` contract + the one-line
   `plugin_playbooks` subscription** (008.009 Phase C / D3). This is the bridge
   that turns a fire into a real run (so a scheduled playbook gets the running
   indicator 008.006 and Stop 008.007 for free). If 008.009 ships it, we just
   consume it; if not, it's a hard dependency for us.

4. **Mode flag** `SCHEDULER_MODE = external | local` (env), defaulting to
   `local` for OSS. In `external` mode: no local tick loop; tools register
   upstream. Hosted sets `SCHEDULER_MODE=external` via provisioning env.

5. **Settings/Schedules UI** (plugin-owned) — reuse 008.009 Phase E; in
   `external` mode it reads the mirror / the control-plane list endpoint.

## Decisions we've already locked on our side (so the contract is stable)

These match the 008.009 posture and are settled — they shape the contract above:

- Source of truth for "when" in hosted is the **control plane** (`external_schedules`);
  the plugin keeps a display **mirror**. (OSS `local`: the plugin's DB is truth.)
- Registration auth = **the agent's existing gateway token** (zero new inbound
  secret). The control plane resolves `agent_id` and scopes every write to it.
- Fire delivery is **signed + idempotent** (Standard Webhooks + `fire_id`).
- Parsing lives where the clock lives: control plane parses cron/NL and computes
  `next_run_at` in `external` mode; the plugin parses in `local` mode. **Same
  expression grammar both sides** so a schedule reads identically.

## The one decision we'd like Luna's team to make (Q1)

**Merge or sibling?** Our recommendation: **fold 008.009 `plugin_scheduler` into
this one `plugin_external_scheduler`** (one plugin, a `mode` flag, add `/fire`),
so OSS and hosted share code and only the clock differs. If the Luna roadmap
prefers to keep `plugin_scheduler` as the local-only one, then what we *strictly*
need added to it is: the **`/fire` ingress + upstream-register hook +
`playbook.run.requested` contract**, so an external clock can drive it. Either
is fine for us — the tool/ingress/event contract above is what we build against.
