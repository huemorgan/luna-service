# plugin-scheduler — Luna plugin for the luna-scheduler service (NEW PROJECT)

> Handoff file. Build in the same new project as `scheduler-service-plan.md`
> and publish to marketplaces.com.ai, modeled on `plugin-whatsapp` v0.7+:
> zero-config self-provisioning through the hosted control plane, vault-held
> credentials, HMAC-verified ingress, plugin-owned settings tab. Target
> Luna's current plugin SDK (manifest + tools + event bus + UI slot).

## Purpose

Give Luna time-based triggers. A trigger runs either an **agent prompt** (as
if the user typed it — full agent loop, approvals, tools) or a **playbook**
(by name, with inputs). Trigger tools are callable by the **agent** and by
**playbook steps**, so playbooks can schedule themselves and each other. The
clock lives in the external `luna-scheduler` service; this plugin is the UX,
the registration client, and the fire receiver.

## UX (the whole setup)

1. Marketplace → install **Scheduler**. Done — the plugin self-provisions.
2. Ask Luna "every weekday at 9am, summarize my inbox" → the agent calls
   `trigger_create` → trigger visible in the plugin tab with its next run.
3. Or open the plugin tab and add/pause/run/delete triggers by hand.

No env vars, no admin page, no vault form.

## Self-provisioning (the 034.1 WhatsApp pattern)

On first need — `on_load` (best-effort, silent) and the settings tab's
Connect button (explicit, surfaces errors) — when no vault config exists and
`LUNA_GATEWAY_URL` + `LUNA_GATEWAY_TOKEN` are present (= hosted Luna):

- `POST {LUNA_GATEWAY_URL}/api/agent/scheduler/connect` (tenant token) →
  `{account_id, secret, service_url}`; store in the vault as
  `plugin_scheduler.account_id` / `.secret` / `.service_url`.
- All config reads are **vault-first**; no plugin-specific env vars exist.
- No gateway token (OSS/self-hosted) ⇒ settings tab shows "requires a hosted
  Luna or a self-run luna-scheduler service" with manual vault fields
  (service_url + account_id + secret) for people who run the service
  themselves. (A fully local clock mode can come later; not v0.1.)

## Service client (`client.py`)

HTTP to `{service_url}/accounts/{account_id}/...`, every request signed:
`x-sched-timestamp` + `x-sched-signature` = `HMAC_SHA256(secret,
"{ts}.{rawBody}")` (empty body ⇒ empty string; golden vectors shared with the
service repo). Timeouts ~10s; on 401/403 surface "reconnect needed" in the
settings tab.

## Tools (agent- AND playbook-callable)

- `trigger_create(name, schedule_expr, action_type, target, inputs=None,
  timezone=None) -> {id, expr_cron, next_run_at}` — expr may be cron or the
  service's NL phrases; invalid ⇒ the service's 422 message is returned
  verbatim so the agent can rephrase. Not gated (creation is benign;
  execution goes through normal approvals at fire time).
- `trigger_list(enabled_only=False) -> [...]` — from the service (source of
  truth), including next/last run.
- `trigger_delete(id)` — gated (destructive).
- `trigger_pause(id)` / `trigger_resume(id)`
- `trigger_run_now(id)` — enqueues a fire; the resulting run still respects
  approvals.

Tool descriptions must say triggers survive restarts and fire even while
this Luna is asleep — the agent should schedule confidently.

## Fire ingress

`POST /api/p/plugin-scheduler/fire` (reached via the luna-service relay,
which forwards the service's raw body + signature headers):

1. Verify HMAC against vault `plugin_scheduler.secret`, 300s skew ⇒ else 403.
2. Idempotency: `fire_id` already seen (local `plugin_scheduler_fires`
   table) ⇒ 200 `{deduped: true}`, no emit. Retries can never double-run.
3. Emit by `action_type`:
   - `playbook` → `playbook.run.requested {name: target, inputs,
     source: "plugin-scheduler"}` — the playbooks plugin's existing
     subscription turns it into a real run (running badge, Stop, approvals).
   - `agent_prompt` → synthetic inbound `message.received
     {channel: "scheduler", sender: "luna-scheduler", text: target}` — the
     normal agent loop picks it up.
4. Record the fire row (fire_id, trigger_id, action, emitted_at, outcome);
   return 200 fast — never run the work in-request.

The plugin emits events and imports nothing from other plugins; if the
playbooks plugin is absent, a `playbook` fire records
`failed: no playbook runner` and the settings tab shows it.

## Settings tab (plugin-owned UI slot)

- Connection strip: Connected (service reachable) / Reconnect needed / the
  OSS manual-config state.
- Triggers table: name, human expr + cron, tz, action (prompt preview or
  playbook name), next run, last run + status, enabled toggle, run-now,
  delete. Add form: free-text expression with parsed-cron preview (server
  parse, debounced), action type, target, inputs (JSON, playbook only).
- Recent fires list (from `GET /accounts/{id}/fires`): time, trigger,
  delivered/deduped/failed.

## Storage (plugin DB)

- `plugin_scheduler_fires` — fire_id PK, trigger_id, action_type, received_at,
  outcome. For idempotency + the tab's history fallback.
- Optional trigger mirror cache for a fast tab render; the service stays the
  source of truth (list always re-fetches).

## Manifest / packaging

- `plugin-scheduler` v0.1.0, type `system`, MIT, published to
  marketplaces.com.ai like plugin-whatsapp; keep `pyproject.toml` and
  manifest versions in lockstep (the 034 drift nit).
- Declares: tools above (playbook-callable), the `/fire` ingress route, the
  settings UI slot, vault keys.

## Tests

- Isolation (MockAgent): create → list → pause → delete round-trip against a
  mocked service; expr 422 surfaced verbatim; tools callable without web UI.
- HMAC: golden vectors (shared with the service), skew rejection, wrong
  secret ⇒ 403.
- Fire: valid playbook fire emits exactly one `playbook.run.requested`;
  agent_prompt fire emits `message.received {channel:"scheduler"}`; replayed
  fire_id ⇒ `{deduped:true}` and no second emit; missing playbooks plugin ⇒
  recorded failure, 200.
- Self-provision: no vault + gateway env present ⇒ connect called once,
  vault populated; OSS (no token) ⇒ manual state, no calls.
- Upgrade: vault keys and fires table survive a version bump.

## Acceptance

Hosted Luna: install from marketplace → tab shows Connected → "every 2
minutes run playbook X" by chat → fires arrive (machine wakes if asleep),
X runs with badge + Stop → a playbook step can call `trigger_create` →
pause stops fires → replay of a delivered fire_id does nothing → uninstall
deletes the account (via `DELETE /api/agent/scheduler/connect`).
