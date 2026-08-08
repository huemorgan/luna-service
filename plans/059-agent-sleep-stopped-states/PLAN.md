# 059 — Agent lifecycle: Sleeping vs Stopped (and stop the wake-failure noise)

## Goal

Give a hosted Luna two *distinct* "not actively serving" states with different
intent, and make the scheduler + UI + wake path honor the difference:

- **Sleeping** — idle to save money, but **still alive**. Wakes on demand:
  a user opening it, an inbound message (WhatsApp/Telegram), or a **scheduled
  beat**. After the work finishes it goes back to sleep. Schedules keep running.
- **Stopped** — the user deliberately turned it off. **No auto-wake.**
  Scheduled beats are **paused** (no daily-heartbeat spend, no wake attempts)
  until the user starts it again.

And fix the flood of `agent_wake_failed "Machine no longer exists"` criticals,
which today fire on *any* `describe()` miss (destroyed **or** a transient Fly
API error) and never distinguish a stopped machine from a deleted one.

## Why now (from the error pull, 7d)

- `agent_wake_failed` "Machine no longer exists" is our #1 critical (~106
  events across 4 agents, still firing). The user's read: those machines are
  **stopped, not deleted**, and the service isn't waking them — it's giving up.
- Root cause in code: `proxy.py:_try_wake_agent` calls `fly.describe()`; `None`
  → immediately `_mark_agent_error("Machine no longer exists")`. `describe()`
  returns `None` on 404 **and** on any HTTP error (`fly_machines.py:502-520`),
  so a flaky API call or a suspended machine can be misread as destroyed. It
  never calls `get_status()` (which *does* distinguish `SLEEPING` vs
  `DESTROYED`).

## Current model (confirmed)

Three layers, lossy (research: [file:lines below]):

| Layer | States | Notes |
|---|---|---|
| Fly machine | started/running, stopped, suspended, created, destroying/destroyed | truth |
| `RuntimeStatus` (`runtime/base.py`) | pending/provisioning/running/**sleeping**/error/destroyed | `stopped`+`suspended`→`sleeping` |
| `Agent.status` (DB, free text) | pending/provisioning/running/**stopped**/error | **no `sleeping`**; `sleeping`→`stopped` collapse |

- Wake is centralized in `proxy.py:_try_wake_agent`; beats reuse it
  (`scheduler_routes.py` fire relay wakes + retries once on HTTPError).
- Fly is provisioned **always-on**: `autostop:"off"`, `min_machines_running:1`
  (`fly_machines.py:250-252`). So "sleep" as a money-saver doesn't exist yet;
  `stopped` today means explicit Stop, billing suspend, or an unexpected Fly
  stop the reconciler flips to `stopped`.
- Scheduler fire relay does **not** check Agent.status first — it always tries
  to fire, then wakes on failure. A `stopped` agent still gets beats fired at
  it (spend + wake attempts).

## Decision: introduce a first-class `sleeping` status + a real sleep mechanism

### A. State machine (persist `sleeping` on Agent)

```
provisioning ──▶ running ⇄ sleeping        (auto: idle-sleep / wake-on-demand)
                   │  ▲         │
             user Stop │        │ wake (user open / message / beat)
                   ▼  │         │
                stopped ◀───────┘           (user intent: OFF, beats paused)
                   │
                error / deleted             (machine gone / teardown)
```

- `running ⇄ sleeping` is **automatic** and cheap; both mean "active", beats ON.
- `stopped` is **only** user- or billing-initiated; beats OFF, no auto-wake.
- `error` reserved for genuinely-gone/broken (destroyed machine, provision fail).

### B. Sleep mechanism — Fly-native autostop/autostart (preferred)

Flip provisioning to let Fly suspend idle machines and auto-start on request:
`autostop:"suspend"`, `autostart:true`, `min_machines_running:0`.

- **Wake-on-open / message / beat** happens for free: any HTTP hitting the
  machine (proxy or scheduler relay → `internal_url`) triggers Fly autostart.
- **Re-sleep** is automatic after Fly's idle window — "scheduler wakes, runs,
  goes back to sleep" falls out of the box.
- Cost: cold-start latency on first request (mitigate with the existing holding
  page for user opens; beats tolerate a few seconds).
- Alternative (Plan B, if autostart proves unreliable for relay traffic): an
  app-side idle reaper (`stop` after N idle minutes) + explicit wake — more
  code, more control. Start with Fly-native; keep reaper as fallback.

### C. Stopped ⇒ pause the beats

The real money sink is daily heartbeats firing at agents nobody's using.

- On **Stop**: luna-service tells luna-scheduler to **pause** this agent's
  schedules (or the fire relay short-circuits: if `Agent.status == "stopped"`,
  return `409 agent_stopped` and **do not wake**, and signal the scheduler to
  back off).
- On **Start**: **resume** schedules.
- Sleeping agents keep schedules ON (that's the whole point — beats wake them).

### D. Fix the wake classifier (kills the false criticals)

In `_try_wake_agent`, replace the `describe() is None → gone` shortcut with
`get_status()`:

- `SLEEPING` (stopped/suspended) → `fly.start()` (normal wake), status→running.
- `RUNNING` → proceed.
- `DESTROYED` (real 404) → `error` "Machine no longer exists" + offer recreate.
- **HTTP/transient error** → retry describe once; do **not** mark gone or emit a
  critical on a single flaky call (downgrade to a warning, let the reconciler
  confirm).
- Skip wake entirely (no beat, no error) when `Agent.status == "stopped"`.

## UI (Dashboard `AgentCard`)

- **Status badge** gains **Sleeping** — distinct from Stopped:
  - Running: green dot "Running".
  - Sleeping: soft/indigo "Sleeping" + zzz/moon icon, subtext "wakes on use &
    schedules".
  - Stopped: grey "Stopped", subtext "schedules paused".
  - Error: red "Needs attention" + recreate action.
- **Actions rework** (clearer than today's Stop/Start pair):
  - Primary toggle **Active ⇄ Stopped**:
    - "Active" = running-or-sleeping, beats ON (default).
    - "Stopped" = off, beats OFF.
  - `Open` on a sleeping agent shows the holding page while it wakes (existing).
  - Keep `Config`, `Usage` (sparkline), `Recreate` (only in `error`).
- **Copy** so users understand the money model: Sleeping = "saving credits,
  still on call"; Stopped = "off, no scheduled activity or charges".
- Optional per-agent toggle: "Keep always awake" (sets `min_machines_running:1`
  for latency-sensitive Lunas) — power-user setting under Config.

## Phases

1. **Wake classifier fix + reconciler** (ship first, stops the false
   criticals): `get_status`-based wake, transient-error tolerance, `stopped`
   short-circuit. Backfill: reconciler stores `sleeping` (not `stopped`) for
   Fly stopped/suspended on agents that weren't user-stopped.
2. **`sleeping` status end-to-end**: DB value, status mapping, `/api/agents`
   payload, UI badge. No behavior change to schedules yet.
3. **Fly autostop/autostart**: provisioning config + a migration/rollout to
   existing machines; verify user-open and beat both wake reliably; confirm
   re-sleep.
4. **Stopped ⇒ pause beats**: scheduler pause/resume on stop/start + fire-relay
   `stopped` short-circuit; usage should show beats stop spending for stopped
   Lunas.
5. **UI rework**: Active⇄Stopped toggle, Sleeping badge, copy, Recreate action.
6. **Verify in prod** (dojo/browser): stop→beats pause & no wake; sleep→beat
   wakes, runs, re-sleeps; open a sleeping Luna→holding page→running; a
   destroyed machine→error+recreate (no critical spam).

## Open questions
- Does luna-scheduler expose a per-agent pause/resume API, or do we gate purely
  in the luna-service fire relay? (Prefer a real pause so we don't even enqueue.)
- Fly autostart reliability for **relay** traffic (server-to-machine) vs edge
  traffic — validate in Phase 3 before trusting it for beats.
- Cold-start budget acceptable for scheduled beats? If not, keep a warm window.

## Risk
- Medium. Autostop/min_machines change touches every machine; stage on one
  agent first. Scheduler pause must be reversible and idempotent. The wake-
  classifier fix alone (Phase 1) is low-risk and independently valuable.
