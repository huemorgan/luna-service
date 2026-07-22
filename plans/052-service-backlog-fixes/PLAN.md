# 052 — service backlog fixes (holding page ship, install hook, 047 approvals, WA voice keys)

Bundle of the open luna-service items surfaced 2026-07-21/22: the finished-but-
uncommitted proxy holding page, the plugin-catalog install hook 401, plan 047
(approval-card resilience, written but unexecuted), and the WhatsApp voice
key design gap found while triaging admin feedback.

## Items

### 1. Ship the proxy wake holding page (already implemented)

`cloud/api/proxy.py` (+121) + `cloud/tests/test_proxy_wake.py` (+69) are done
and green (12/12). Commit as-is; push deploys luna-service via the deploy hook.

### 2. Plugin-catalog install hook — proxy-login exchange (fix `plugin_installed:false`)

- Bug: `cloud/api/gateway_env_delta.py:61-69` installs via
  `_tenant_request(... "POST /api/p/plugin-marketplace/install")`, which sends
  only `x-luna-proxy-secret` + `x-luna-user` (`cloud/api/agent_routes.py:143-191`).
  Agent core requires an agent-issued JWT for writes → 401 → `plugin_installed:false`.
- Fix: teach `_tenant_request` to perform the proxy-login exchange for writes —
  `POST {internal}/api/auth/proxy-login` with the same headers → `access_token`
  → `Authorization: Bearer` on the actual call. Pattern already proven in
  `cloud/billing/benchmark.py:63-96` (`HttpAgentDriver.login`).
  Implement as opt-in param (`auth="jwt"`) so read-only callers keep one round trip.
- Tests: new coverage for `POST /api/admin/plugin-catalog/install` and
  `apply_gateway_env_delta` (none exist today) — mock machine that 401s writes
  without Bearer and 200s with it; assert `plugin_installed:true` and that the
  login call happened once.

### 3. Execute plan 047 — approval-card resilience (luna repo)

See `plans/047-approval-card-resilience/PLAN.md` for the incident + root cause
(NullPool per-request TLS connects; transient connect failures surface as raw
500 from plugin_approvals routes; the card UI has no retry/reconcile/dismiss).

Recon facts (2026-07-22): `GET /api/p/plugin-approvals/{id}` already exists and
returns `status` (routes.py L643-680) and is wired in the UI client
(`api.approvals.get`, api.ts L556) — the card just never uses it. Error mapping
today: KeyError→404, ValueError(already decided)→409, everything else raw 500.
Card bugs: success path never clears `busy` (relies on parent `decided` prop);
a 409 shows as an error though it means "someone already decided"; X is a
reject API call. `LUNA_DB_POOL=1` pooled engine ALREADY exists in
`luna/luna/data/__init__.py` L37-48 (pool_size env-tunable, pre-ping) — it's
just not enabled on hosted machines.

Server (`luna/plugins/plugin_approvals/routes.py`):
- Wrap approve/reject/get/list DB access: retry once on connection-establishment
  errors (asyncpg/`OperationalError` connect family); persistent failure → 503
  (not 500) so clients can distinguish "retry" from "bug".

UI (`luna/ui/src/views/InlineApprovalCard.tsx`):
- 409 on approve/reject = already decided → reconcile via `approvals.get` and
  collapse, not an error.
- On 5xx/network failure: auto-retry the decision (1s/3s/8s), and reconcile via
  GET between tries (the server may have committed despite the failed response).
- X = local dismiss (collapse locally; stays in Approvals panel). Reject stays
  an explicit button.
- While an error is showing: poll `approvals.get` every ~10s; collapse when it
  resolves server-side.
- Clear `busy` deterministically (own `resolved` state, not only parent prop).

Infra (047 item 6): hosted machines run single-loop `luna serve` → enable
`LUNA_DB_POOL=1` with conservative sizing (`LUNA_DB_POOL_SIZE=3`,
`LUNA_DB_MAX_OVERFLOW=5`; per-tenant role cap is 20, one machine per tenant) as
image env (Dockerfile) so it rides the same image roll. Verify single-loop
before flipping; otherwise defer with findings.

Tests: pytest route tests (crib `tests/008.003-blanket-approvals/test_routes_scopes.py`
harness): connect-error → one retry → success; two failures → 503; 409 passthrough.
Vitest (`ui/`, RTL, crib `045-plan-card.test.tsx`): 409 collapses card; 500→retry
→success; X collapses locally without network; error-state poll collapses on
remote resolve; busy cleared. Dojo (playwright .mjs, crib
`dojo/tests/039-policy-block/walkthrough.mjs`): live instance, route-intercept
approve → 500 twice then pass-through; assert card self-heals, never stuck,
X always collapses.

### 4. WhatsApp voice — per-account ElevenLabs keys (close the design gap)

Gap: wa-gateway synthesizes voice with a single platform env key
(`ELEVENLABS_API_KEY`, set 2026-07-21); tenant-scoped elevenlabs keys in
`gateway_keys` are never used; `connect_gateway_key` never affects voice.

wa-gateway repo (huemorgan/luna-whatsapp, local clone `../luna-whatsapp`):
- Schema: `whatsapp_accounts` + `eleven_key text`, `eleven_voice_id text`
  (ALTER IF NOT EXISTS, matching existing migration style in db.js).
- `PATCH /accounts/:id` accepts `eleven_key`, `eleven_voice_id` (admin-key auth).
- Both synthesis sites (`index.js /send-voice` non-outbox path, `session.js`
  outbox delivery) build cfg: account key/voice → fallback to `config.eleven`.
  `voiceEnabled` check becomes per-account (account key OR env key).
- Tests: extend `gateway/test/voice.test.mjs` + `gateway.test.mjs` (node --test).

luna-service side:
- On `POST /api/agent/whatsapp/connect` (`cloud/api/whatsapp_agent_routes.py`):
  after account create, resolve the agent's effective elevenlabs key
  (`resolve_keys` — agent scope first, then global) and PATCH it (+ voice id if
  any) onto the wa account. Best-effort; never fails the connect.
- On admin `add_key` for `elevenlabs` with `agent:` scope
  (`cloud/api/gateway_admin_routes.py:212`): push to that agent's wa account if
  plugin-whatsapp is installed. Best-effort.
- Tests: connect pushes key; connect without key pushes nothing; agent-scoped
  add_key pushes; global add_key doesn't.

### 5. Out of scope

- 050 notes (scheduler dev inspection endpoint, trigger-name uniqueness) — not
  bugs, revisit on demand.
- Core jobs-suite bugs (luna/plans/046) — separate effort, starts with BUG-L.

## Verification / deploy

1. Full `cloud/` pytest suite green; wa-gateway `node --test` green; luna
   plugin_approvals pytest + UI tests green.
2. Dojo browser pass on the approval card flows (local instance).
3. Deploy order:
   a. luna-service: commit + push (deploy hook fires); verify `/healthz`,
      holding page on a stopped agent, install hook on a live agent.
   b. wa-gateway: push main (autoDeploy=yes); verify accounts reconnect and
      per-account voice key honored (Rayla).
   c. luna agent image: admin build → promote → migrate fleet (045 phase06
      procedure); expect the SSE reconnect wave, verify approvals UI on a
      canary agent first.
