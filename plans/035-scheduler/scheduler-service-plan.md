# luna-scheduler — always-on trigger service (NEW PROJECT)

> Handoff file. Build this in a **new repo** (`luna-scheduler`), modeled on
> `luna-whatsapp`'s gateway (`luna-wa-gateway`): a small always-on Render web
> service with a Postgres DB, multi-account, per-account HMAC, an admin API,
> and `/stats` for the luna-service monitoring page. The companion
> `scheduler-plugin-plan.md` specs the Luna plugin that consumes this service.

## Purpose

Hosted Lunas run on ephemeral Fly machines that sleep when idle, so they
cannot keep their own cron. This service is the fleet's clock: it stores
**triggers** (one Luna = one account, many triggers), ticks, and at fire time
delivers a signed webhook that wakes the Luna and runs the work. It never
runs work itself — it only fires.

## Stack

- Python 3.12 + FastAPI + SQLAlchemy(async) + Alembic + Postgres, `croniter`
  for cron math. One Render **web service** (always-on, no scale-to-zero) +
  Render Postgres. `render.yaml` blueprint in-repo.
- Env: `DATABASE_URL`, `ADMIN_KEY` (generate once, share with luna-service as
  `CLOUD_SCHEDULER_SERVICE_ADMIN_KEY`), `TICK_INTERVAL_S` (default 15),
  `PORT`.

## Data model

- `accounts`: `id` (the account_id string — the Luna's slug, PK), `secret`
  (per-account HMAC secret, generated server-side), `fire_url` (where fires
  are POSTed — luna-service's relay for that agent), `enabled`,
  `daily_fire_cap` (default 200), `created_at`.
- `triggers`: `id uuid PK`, `account_id FK`, `name`, `expr_raw` (what the
  user typed), `expr_cron` (canonical), `timezone` (IANA, default UTC),
  `action_type` `'agent_prompt' | 'playbook'`, `target` (prompt text or
  playbook name), `inputs jsonb` (playbook inputs), `enabled`,
  `min_interval_s` (default 60, floor enforced at create),
  `next_run_at` (indexed), `last_run_at`, `created_by`, `created_at`.
- `fires`: `id uuid PK` (= `fire_id`), `trigger_id FK`, `account_id`,
  `due_at`, `fired_at`, `status` `'pending'|'delivered'|'failed'|'dead'`,
  `attempts`, `last_error`, `response_status`. Doubles as outbox and history.

## Expression engine (`expr.py`)

- `parse(raw, tz) -> cron`: try cron via `croniter`; else a small explicit NL
  phrase list — `every minute`, `every N minutes/hours`, `every hour`,
  `every day at HH:MM`, `every weekday at HH:MM`, `every <weekday> at HH:MM`,
  `every weekend at HH:MM`, `on the 1st of every month at HH:MM`. Anything
  else ⇒ `422 invalid_expression` with a helpful message. No LLM — small,
  predictable, free; users can always write cron.
- `next_run(cron, tz, after) -> datetime` (UTC). Test across DST boundaries,
  leap day, end-of-month.

## Ticker

Asyncio task in the app lifespan (skipped under tests):

- Every `TICK_INTERVAL_S`: `SELECT … FROM triggers WHERE enabled AND
  next_run_at <= now()` with `FOR UPDATE SKIP LOCKED` (HA-safe if the
  service ever runs >1 instance).
- Per due trigger: insert a `fires` row (new `fire_id`), recompute and store
  `next_run_at` **before** delivery (a delivery failure must not stall the
  schedule). Overdue by more than one interval ⇒ fire **once**, log a
  warning — never catch-up storms.
- Enforce `daily_fire_cap` per account (cap hit ⇒ fire recorded as `failed`
  with `cap_exceeded`, trigger stays scheduled).
- Record `last_tick_at` (exposed in `/stats` — luna-service alerts on lag).

## Fire delivery

Worker drains `pending` fires:

- `POST {account.fire_url}` with JSON body
  `{fire_id, trigger_id, account_id, action_type, target, inputs, due_at,
  fired_at}`.
- Signed like the WhatsApp gateway: `x-sched-timestamp` (unix seconds) +
  `x-sched-signature` = `HMAC_SHA256(account.secret, "{ts}.{rawBody}")`,
  300s skew window on the verifying side.
- 2xx ⇒ `delivered`. Else exponential backoff (e.g. 30s, 2m, 10m, 30m; ~6
  attempts) ⇒ `dead` with `last_error`. Timeout generous (~120s) — a fire
  can start a long agent turn on a cold machine. The plugin dedupes on
  `fire_id`, so retries can never double-run.

## API

**Admin (`x-admin-key == ADMIN_KEY`)** — called only by luna-service:

- `POST /accounts` `{account_id, fire_url}` → creates (or returns existing)
  account; response includes `secret` **only on create/rotate**. Idempotent.
- `GET /accounts` · `PATCH /accounts/{id}` (fire_url, enabled, cap,
  `rotate_secret: true`) · `DELETE /accounts/{id}` (cascades triggers/fires).
- `GET /stats` → `{version, uptime_s, last_tick_at, db: {ok, latency_ms},
  totals: {accounts, triggers_enabled, triggers_paused, fires_1h, fires_24h,
  failed_24h, dead_24h}, upcoming: [next ~20 {due_at, account_id,
  trigger_name}], accounts: [{account_id, enabled, triggers, next_run_at,
  last_fire_at, last_fire_status, fires_24h, sent_today, daily_cap}]}`.
- `GET /triggers?account_id=` → fleet-wide trigger list (feeds the
  luna-service admin page).
- `GET /health` (no auth) → `{status: "ok", db: bool}`.

**Account-scoped (per-account HMAC, same scheme as fire delivery, headers on
the request; caller is `plugin-scheduler` on the Luna machine)** — the path
`account_id` must match the authenticated account:

- `POST /accounts/{id}/triggers` `{name, expr, timezone?, action_type,
  target, inputs?}` → parses expr, returns `{id, expr_cron, next_run_at}`.
- `GET /accounts/{id}/triggers` (+ per-trigger recent fires)
- `PATCH /accounts/{id}/triggers/{tid}` (any field; expr re-parsed)
- `DELETE /accounts/{id}/triggers/{tid}`
- `POST /accounts/{id}/triggers/{tid}/pause|resume`
- `POST /accounts/{id}/triggers/{tid}/run-now` → enqueue a fire immediately
  (still capped, still idempotent downstream)
- `GET /accounts/{id}/fires?limit=` → fire history for the settings tab

## Security posture

- Admin key: only luna-service holds it; controls account lifecycle.
- Account secret: generated here, returned once, held by that tenant's vault;
  scopes both trigger CRUD (inbound) and fire verification (outbound). A
  leaked secret exposes one Luna's triggers, nothing else.
- No unauthenticated write surface. `/health` is the only open endpoint.
- Rate-limit trigger CRUD per account (it is not a hot path).

## Tests

- expr: cron passthrough, each NL phrase, invalid ⇒ 422; DST/leap/EOM next-run.
- ticker: due selection, SKIP LOCKED single-fire under two workers, overdue
  fires once, `min_interval_s` rejected at create, daily cap.
- delivery: signature correctness (golden vectors shared with the plugin),
  backoff to dead-letter, `next_run_at` advances even when delivery fails.
- API: admin-key auth, account HMAC auth (skew, wrong secret, cross-account
  path mismatch ⇒ 403), idempotent account create, secret only on create.
- `/stats` shape frozen with a snapshot test — luna-service builds against it.

## Milestones

1. Repo + FastAPI skeleton + DB + Alembic + `/health` + `render.yaml`; deploy.
2. Accounts + admin API + `/stats` (empty numbers ok) — unblocks the
   luna-service admin page.
3. expr + triggers CRUD (HMAC) — unblocks the plugin.
4. Ticker + delivery + retries/dead-letter; golden signature vectors.
5. Hardening: caps, rate limits, `/stats` fleshed out, README with the
   integration contract.

## Non-goals

- No workflow engine — multi-step scheduled work is a playbook on the Luna.
- No exactly-once beyond SKIP LOCKED + `fire_id` idempotency; a missed window
  fires once on recovery, never N times.
- No per-tenant UI here — the plugin and the luna-service admin page are the
  only UIs.
