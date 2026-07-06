# 035 cross-repo review — scheduler-service/plugin side → luna-service

From the team that built `scheduler-service` + `plugin-scheduler`
(both at 001-mvp: unit tests green, live browser E2E green against a real
Luna). We read `d419160` (fire relay, self-service connect, admin page).
Overall: the relay design, secret-once connect, and never-5xx admin
envelopes are exactly right. Three concrete items, two already absorbed on
our side.

## 1. FIXED ON OUR SIDE — `GET /accounts/{account_id}` now exists

`agent_status` in `scheduler_agent_routes.py` reads
`GET /accounts/{slug}`. The service originally only had list/patch/delete,
so that GET returned **405** (not 404), which your code maps to a 502.
We added the route. Response (200):

```json
{"account_id": "...", "fire_url": "...", "enabled": true,
 "daily_fire_cap": 200, "created_at": "...",
 "triggers": 2, "next_run_at": "...", "last_fire_at": "...",
 "last_fire_status": "delivered", "fires_24h": 24, "sent_today": 5,
 "daily_cap": 200}
```

Flat object (no `account` wrapper — your unwrap branch handles both),
404 `{"detail": "no such account"}` for unknown ids, never includes the
secret. Every field your `/api/agent/scheduler/status` projects is there.

## 2. CHANGE REQUESTED — admin `/triggers` returns an object, not an array

Service `GET /triggers` (admin key) returns:

```json
{"triggers": [ {...}, ... ]}
```

`service_triggers` in `scheduler_routes.py` does
`triggers = env.pop("stats")` and returns that verbatim, so the browser
gets `{"triggers": {"triggers": [...]}}`; `SchedulerPage.tsx`'s
`Array.isArray(body.triggers)` then renders an empty table. One-line fix:

```python
triggers = env.pop("stats")
return {**env, "triggers": triggers.get("triggers", [])}
```

(and the mock in `test_scheduler.py::test_triggers_list` should wrap its
rows as `{"triggers": rows}`). We'd rather keep the enveloped shape on the
service — every service endpoint returns an object, which leaves room for
pagination/cursors later. `/stats` needs no change: your page's
expectations match our shape exactly (verified field-by-field).

## 3. CHANGE REQUESTED — secret recovery path for re-installs

`POST /api/agent/scheduler/connect` is idempotent and only reveals the
secret on first creation (good). But when a tenant loses its vault (machine
rebuild, plugin reinstall), connect returns 200 **without** a secret and
the plugin is stuck — the service account exists, nobody knows the secret.
The plugin now surfaces this as an actionable error instead of crashing,
but recovery needs your side. Suggestion: accept `{"rotate": true}` on
connect (or a `POST /api/agent/scheduler/rotate`), forwarding to the
service's existing `PATCH /accounts/{slug} {"rotate_secret": true}`, which
returns the new secret exactly once. Auth is already the device token, and
rotation invalidates nothing but the lost secret, so this is safe.

## Confirmed aligned (no action)

- **Fire relay**: forwarding raw bytes + `x-sched-*` headers and returning
  the upstream status verbatim is exactly what our retry machinery needs —
  the plugin ACKs 200 fast (emit happens in a background task), so the
  120s relay timeout will practically never be hit; 502/504 from the relay
  → our backoff (3 attempts) → dead-letter, and retries reuse the same
  `fire_id`, which the plugin dedupes. Verified live.
- **`POST /accounts`** contract: 200, `{account_id, ..., secret?}` with
  secret only on creation, idempotent re-create updates `fire_url` —
  matches your `provision._service` call. (`status` isn't a field we
  return; we do return `"created": true|false` if you want it.)
- **HMAC**: hex `HMAC_SHA256(secret, "{ts}.{rawBody}")`, 300s skew.
  Golden vectors: `vectors/hmac_vectors.json` in both of our repos —
  feel free to copy for relay tests.
- The relay URL scheme `/api/webhooks/scheduler/{slug}/fire` as the
  registered `fire_url`, and account_id == agent slug: adopted as-is in
  our mental model; plugin never assumes anything about fire_url.
