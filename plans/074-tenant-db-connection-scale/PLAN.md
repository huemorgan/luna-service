# 074 — tenant DB connections: from ~40 Lunas to 100+ (trim now, PgBouncer next)

## Where we are (2026-08-17)
- luna-tenant-prod (Render pro_4gb, Oregon): `max_connections = 103`.
- 37 Fly machines (`luna-agents`, all `sjc`), one Postgres role + DB each.
  Fleet pool: `LUNA_DB_POOL=1`, `LUNA_DB_POOL_SIZE=2`, `LUNA_DB_MAX_OVERFLOW=3`,
  `pool_recycle=300`. Census today: 28 backends for 37 machines (~0.8 each,
  1–4 on the busy ones).
- Per-role guardrails (071 + 073): `CONNECTION LIMIT 12`,
  `idle_session_timeout`, `idle_in_transaction_session_timeout = 5min`,
  TCP keepalives 30/10/3. Alert `tenant_db_saturation` at >80 backends.
- Extrapolation: 100 machines × 1–2 idle-held connections = 100–200 baseline
  → over the cluster limit somewhere around 60–80 active Lunas, earlier under
  bursts. Bigger Render plan only moves the line linearly.

## Phase A — trim (this plan executes it)
1. `idle_session_timeout` 15min → **5min** on every tenant role. The client
   already recycles anything idle >5 min at next checkout (`pool_recycle=300`),
   so the server closing it at 5 min is invisible to luna and drops the
   held-idle baseline by roughly half. Applied live to all 77 roles; the
   provisioner (`ROLE_SETTINGS`) and `scripts/tenant_role_settings.py` carry it.
2. Pool sizes stay 2/3. Going to 1/2 would cap a Luna at 3 concurrent
   sessions; a turn + scheduled trigger + attachment-summary task already
   overlap, and SQLAlchemy would then block up to `pool_timeout` (30 s) — a
   worse failure than the one we are avoiding. Revisit only with data from the
   census.
3. luna 079 (0.82.005) disposes the engine on shutdown → restarts stop
   leaving orphans at all.

Expected effect: baseline ≈ 0.5/machine steady, ~1 under activity → ~100
Lunas fit with margin for bursts; the alert at 80 still stands.

## Phase B — PgBouncer (plan; execute when census >50 or fleet >60)

### Where it runs
Decision: **on Fly, in the `luna-agents` org, as its own app `luna-pgbouncer`,
region `sjc`, 2 machines** — not on Render.
- Render's own pooler for luna-tenant-prod would be the least work, but it is
  not enable-able through the API (dashboard/support only) and it sits on the
  DB host, so every Luna still crosses Fly→Render per query exactly as today.
- On Fly the pooler is on the machines' private network (`.internal`, ~1 ms),
  and only pgbouncer holds the long-lived TLS connections to Render. Two
  machines behind Fly internal DNS (`luna-pgbouncer.internal`) give HA; each
  runs the same config, so either can die.
- A Render web/private service could host pgbouncer too, but Render private
  services are not reachable from Fly, so it would have to be public + TLS —
  no advantage over Render's own pooler.

### Config
- `pool_mode = transaction`, `max_client_conn = 4000`,
  `default_pool_size = 3` (per tenant user/db), `reserve_pool_size = 2`,
  `server_idle_timeout = 60`, `server_lifetime = 1800`, `ignore_startup_parameters = extra_float_digits`.
- pgbouncer ≥ 1.21 with `max_prepared_statements = 200` (asyncpg uses
  prepared statements; alternatively `prepared_statement_cache_size=0` in
  luna's connect args — one line in `luna/data/__init__.py`, gated on an env
  var so local/dev keeps the cache).
- Server side: `CONNECTION LIMIT` per role must be ≥ pool_size+reserve
  (12 already is). Cluster total server conns ≈ tenants_active × 3, capped by
  pgbouncer, so `max_connections=103` covers ~30 simultaneously active tenants
  and queues the rest for milliseconds — the whole point.
- TLS: `server_tls_sslmode = require` to Render; client side plain inside
  Fly's private network (WireGuard-encrypted mesh).

### Auth (the non-trivial part on Render)
pgbouncer must authenticate each tenant role. `auth_query` needs a
SECURITY DEFINER function reading `pg_shadow`, which needs a superuser to
create — Render gives none. So: **auth_file managed by the control plane.**
- The CP already generates every tenant password (`provision_tenant_database`)
  and stores the DSN it hands to the machine; it can render `userlist.txt`
  (`"role" "SCRAM-SHA-256$..."` — compute the verifier CP-side, never ship
  plaintext).
- New internal endpoint `GET /api/internal/pgbouncer/userlist` (bearer =
  `PGBOUNCER_SYNC_TOKEN`), and the pgbouncer image runs a 30 s sidecar loop:
  fetch → if changed write file → `pgbouncer -R` / SIGHUP. Provisioning a new
  agent becomes usable on the pooler within ≤30 s; the provisioner can also
  poke the endpoint's `/reload` to make it immediate.

### Cut-over
1. Deploy `luna-pgbouncer` (Dockerfile in `infra/pgbouncer/`, `fly.toml`,
   secrets `PGBOUNCER_SYNC_TOKEN`, `RENDER_DB_HOST`); verify with one role via
   `psql` from a test machine.
2. Provisioning: `LUNA_DATABASE_URL` host → `luna-pgbouncer.internal:6432`
   (env_manifest change; `DYNAMIC_VARS` unchanged — only the host template).
3. Canary: `env/backfill?slugs=<one vaselin agent>&keys=…` after flipping the
   template; run the tenant for a day; watch `chat.ttft`, `SHOW POOLS`.
4. Fleet backfill (in-place restart per machine, ~4 min each — do it in
   batches during quiet hours; 073 keepalives + 079 make restarts safe).
5. Alerts: pgbouncer `SHOW STATS` scraped into `/api/admin/pricing/ops`
   (cl_active, sv_active, avg_wait); alert on `avg_wait > 50 ms`.

### Out of scope
Sharding tenants across clusters / per-tenant SQLite (needed past ~300–1000
tenants) — separate plan when the pooler shows the cluster itself is the
bottleneck (CPU/IO, not connections).
