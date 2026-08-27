# Phase 2 — execution summary

Commit: `44b0725` ("076 phase 2: agent mint API + public webhook ingress"), local only —
pushed to main in phase 4 (deploy) so Render deploys once, with the whole feature.

## What shipped

**`cloud/api/webhook_agent_routes.py`** (new) — agent-facing mint API at
`/api/agent/webhooks/hooks`, device-token auth using the same `_bearer` /
`verify_token` pattern as the scheduler agent routes (plan 035):

- `POST /hooks` — idempotent upsert keyed on (agent, plugin, name). The per-hook
  secret (`token_urlsafe(32)`) is returned **only** on first create or when
  `{"rotate": true}` is passed; it is never readable afterwards. `hook_slug` is an
  unguessable `token_urlsafe(18)`. Validation: name/plugin `^[a-z0-9][a-z0-9_-]{0,63}$`,
  `target_path` must start with `/api/p/` (plugin routes only — the hook can never be
  pointed at an admin or core route), mode `sync|queue`. Also appends the plugin to the
  agent's `installed_plugins` bookkeeping so the admin machines page stays truthful.
- `GET /hooks` — list without secrets. `PATCH /hooks/{hook_slug}` — enable/disable.
  `DELETE /hooks/{hook_slug}`.
- `public_hook_url()` builds `{base}/api/webhooks/hooks/{agent_slug}/{hook_slug}` from
  the new `CLOUD_WEBHOOKS_BASE_URL` setting (empty ⇒ `base_url`), so a vanity host can
  be added later without touching code.
- Registered twice in `cloud/main.py` — bare and under `/proxy` — because hosted
  machines get `LUNA_GATEWAY_URL = <base>/proxy` (035 precedent).

**`cloud/api/webhook_routes.py`** (new) — the public ingress
`GET|POST /api/webhooks/hooks/{agent_slug}/{hook_slug}`:

- Auth is the unguessable hook_slug (same trust model as the 035 fire relay). Unknown
  hook → 404, disabled → 410, body > 200 KB → 413.
- **sync** mode: forwards the raw body + query string to
  `{internal_url}{target_path}` with provider headers passed through minus a denylist
  (authorization, cookie, hop-by-hop, and any `x-luna-*`/`fly-*`/`webhook-*` — so a
  caller can't spoof our internal headers), plus a standard-webhooks signature
  (`webhook-id`/`webhook-timestamp`/`webhook-signature`) signed with the per-hook
  secret, `x-luna-hook-name`, `x-luna-hook-plugin`, `x-luna-proxy-secret`, and
  `fly-force-instance-id`. On transport error: `_try_wake_agent` → `_wait_machine_ready`
  (poll `/api/health` ≤45 s, the phase-1 readiness wait) → retry **once** → 502.
  `ReadTimeout` → 504 with **no retry** (the request may have executed — double-run
  risk, 035 rule). The machine's response is returned to the caller verbatim, so
  provider challenge handshakes (echo a token) work end-to-end.
- **queue** mode: builds a JSON envelope (`hook`, `plugin`, `received_at`, `method`,
  `query`, `headers`, `body` or `body_b64`, and `signature` = HMAC-SHA256 of the raw
  body with the hook secret), inserts a `RelayDelivery` with `target_path`, returns
  202. The phase-1 forwarder delivers it with wake + backoff + dead-letter.
- Per-hook stats (`delivery_count`, `last_delivery_at`, `last_status_code`) bumped
  best-effort.

**`cloud/config.py`** — `webhooks_base_url` setting (env `CLOUD_WEBHOOKS_BASE_URL`).
**`cloud/tests/conftest.py`** — `webhook_routes.get_db_session` added to `_patch_db`.
**`cloud/tests/test_webhooks.py`** (new, 18 tests) — mint CRUD/auth/validation, ingress
404/410/413, sync forwarding with a signature the test actually verifies via
`standard_webhooks.verify`, header hygiene, GET challenge passthrough, wake-retry and
wake-fail paths, queue envelope contents, stats.

## Verification

- `cloud/tests/test_webhooks.py` — 18/18 pass.
- Full suite: **790 passed, 9 skipped, 1 failed** — the failure is
  `test_billing_stripe_clawback.py::test_refund_of_spent_credits_creates_debt_repaid_by_next_grant`,
  the pre-existing baseline failure recorded in phase 0. No regressions.
- Real-environment verification is deliberately deferred to phase 4 (production smoke
  test after deploy): this API is only reachable with a device token from a hosted
  machine, and the QA plan mints via a real tenant.

## Surprises / learnings

- **Two test-isolation traps, both in conftest's shared in-memory SQLite.** (1) New
  modules that import `get_db_session` directly must be added to `_patch_db` or every
  request 500s with "no such table". (2) Subtler: `issue_token` only *flushes*; the
  app's own sessions share the single `:memory:` connection (StaticPool), so when an
  app session closes it can roll back the test session's uncommitted token insert —
  the token then works for one request and 401s on the next, but only when other tests
  had run first. Symptom was maddening (`KeyError: 'hooks'` / 401 mid-test, passes in
  isolation). Fix: the test helper commits after `issue_token`. Recorded here because
  any future test that issues device tokens will hit the same thing.
- FastAPI's double registration (bare + `/proxy`) worked unchanged for a new router —
  no special handling needed.

## Reassessment of remaining phases

- Phase 3 (admin API + UI) unchanged: `webhook_admin_routes.py` (require_admin), a
  Webhooks page in SERVICE_ITEMS, and a "Minted hooks" section in MachinesPage's
  existing WebhooksTab. The `_endpoint_out` shape from this phase is reusable for the
  admin listing (plus agent name/slug).
- Phase 4 (deploy) unchanged: push both local commits, Render autodeploys, migration
  0016 applies via migrate.py; production smoke per plan.
- No changes to PLAN.md required.
