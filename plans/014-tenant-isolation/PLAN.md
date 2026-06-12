# Plan 014 — Hard Tenant Isolation

Every Luna machine must be a sealed box. The agent inside can wreck, scan, or
run arbitrary plugin code against everything it can reach — and the blast
radius must end at its own walls. Isolation is **enforced by infrastructure
credentials**, never by asking the Luna image to behave.

Origin: during the 013 gateway walkthrough we discovered that all Fly machines
share one Postgres user (`luna_tenant`) and one schema (`public`). A fresh
test agent displayed another user's conversation. The first proposed fix
(`luna/plans/007-provider-base-url/007.003.../RECOMMENDATION.md`) asked Luna
to honor `LUNA_DB_SCHEMA` — but that's trust-the-client security. A
non-compliant, old, or malicious image ignores the env var and the breach is
back. This plan moves enforcement to where the tenant can't opt out.

---

## Design principle

> **The machine can only do what its credentials allow.**
> Anything the tenant could break by ignoring a convention, we don't protect
> with a convention.

A tenant machine should perceive: *one database that is entirely mine, one
filesystem that is entirely mine, API endpoints that only answer for me.*
Whatever it does inside that box — DROP every table, scan the catalog, run a
malicious plugin — nothing outside the box is reachable.

## Why per-tenant DATABASE, not per-tenant schema

Two candidate models on the existing Render Postgres instance (`luna-tenant-prod`):

| | Role + schema | Role + **database** (chosen) |
|---|---|---|
| Data access isolation | Yes (GRANTs) | Yes (can't even connect elsewhere) |
| Catalog invisibility | **No** — `pg_class` still lists other tenants' table names | Yes — only own DB's objects visible |
| Cross-tenant queries | Blocked by GRANTs (one misconfigured GRANT = leak) | Impossible in Postgres, period |
| "Thinks the DB is hers" | No (sees other schemas exist) | Yes |
| Ops cost | Lower | Slightly higher (extensions per DB) |

We choose **one database + one role per agent**. Postgres cannot query across
databases without dblink/FDW (which tenant roles won't have). A leaked GRANT
can't happen because there is nothing to GRANT across. The only residual
visibility is the list of database *names* in `pg_database` — acceptable.

Verified: `luna_tenant` on `luna-tenant-prod` has `CREATEDB` and `CREATEROLE`,
so the control plane can do all of this with existing credentials.

## What a machine holds today vs after

| Env var | Today | After 014 |
|---|---|---|
| `LUNA_DATABASE_URL` | Shared `luna_tenant` superuser-ish creds → whole instance | Per-agent role, can connect **only** to its own DB |
| `LUNA_DB_SCHEMA` | Advisory, ignored by Luna | Dropped (meaningless — the DB is theirs) |
| `LUNA_TRUSTED_PROXY_SECRET` | **Shared across all agents** | Per-agent secret |
| `LUNA_VAULT_MASTER_KEY` | Per-tenant (HKDF from root key) — already good | Unchanged |
| `LUNA_{SVC}_API_KEY` | Per-agent `lsv1-` gateway token (013) — already good | Unchanged |
| Volume / filesystem | Per-machine Fly volume — already good | Unchanged |

The shared trusted-proxy secret matters because Fly machines in one app share
a private 6PN network: malicious code on machine A can reach machine B's
:8000 directly, and today it holds the secret that machine B trusts. Per-agent
secrets close this.

---

## Phase A — Provisioner v2: database + role per agent

`cloud/db/tenant_provisioner.py` replaces `provision_tenant_schema` with
`provision_tenant_database(agent_slug)`:

1. `CREATE ROLE "luna_a_{slug}" LOGIN PASSWORD '{random 32 bytes}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT CONNECTION LIMIT 10`
2. `CREATE DATABASE "luna_a_{slug}" OWNER "luna_a_{slug}"`
3. `REVOKE CONNECT ON DATABASE "luna_a_{slug}" FROM PUBLIC` then
   `GRANT CONNECT ... TO "luna_a_{slug}"`
4. Connect to the new DB as `luna_tenant` and
   `CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS "uuid-ossp"`
   (extensions need elevated rights; the tenant role can't install them)
5. Idempotent: re-running on an existing agent re-uses DB/role, rotates the
   password (machines get the fresh one on every provision/update)

The role password is **not stored** in the control-plane DB — it's generated
at provision time, injected into the machine env, and rotated on every
re-provision. If we ever need it, we re-provision.

`cloud/provisioning/workflow.py`:
- builds `LUNA_DATABASE_URL = postgresql+asyncpg://luna_a_{slug}:{pw}@{host}/luna_a_{slug}`
- stops injecting `LUNA_DB_SCHEMA`
- `Agent.db_schema` column becomes `Agent.db_name` (or keep column, store DB name)

Also: `REVOKE CONNECT ON DATABASE lunatenants FROM PUBLIC` — only `luna_tenant`
(control plane) may touch the old shared DB from now on.

## Phase B — Per-agent trusted proxy secret

- Derive per agent: `HKDF(CLOUD_TRUSTED_PROXY_SECRET, info=agent_id)` — no new
  storage, control plane can always recompute.
- `cloud/api/agent_proxy` (the `/a/{slug}/` path) sends the agent-specific
  secret in the trusted-proxy header for that agent.
- Machines get their own secret in `LUNA_TRUSTED_PROXY_SECRET`.
- Result: a request forged from machine A to machine B over 6PN fails auth.

No Luna change needed — Luna already compares the header against its env var.

## Phase C — Migrate the existing fleet

8 running machines, all on the shared user + `public` schema.

1. **Backup first (hard rule):** `pg_dump` the full `lunatenants` database to
   a dated archive before touching anything. Keep it off-repo.
2. For each agent: run provisioner v2 → new DB + role; update the Fly machine
   env (`LUNA_DATABASE_URL`, `LUNA_TRUSTED_PROXY_SECRET`, drop
   `LUNA_DB_SCHEMA`); restart machine. Fresh DB migrates cleanly (0.08.002
   fixed the fresh-DB alembic path).
3. **Data:** rows in `public` cannot be attributed to individual agents (no
   agent_id on Luna tables) — they stay in the archive, agents start fresh.
   Acceptable: early alpha, all current agents are tests or near-fresh.
   Exception — three legacy schemas hold attributable data:
   - `luna_user_alonna_my_luna` → agent `alonna-my-luna` (active): dump schema,
     restore into her new DB so she keeps her history.
   - `luna_user_vaselin`, `luna_user_vaselin_my_luna` → no matching live agent;
     archive only.
4. **Rotate `luna_tenant`'s password** (Render dashboard) after all machines
   are off it — every old machine env held it, so until rotation the old
   credential remains a skeleton key. Update `CLOUD_TENANT_DATABASE_URL` on
   Render and locally.
5. After a soak period (1 week, user confirms): drop the leftover
   `luna_user_*` schemas and truncate `public` tenant tables in `lunatenants`.
   Never before the backup from step 1 is verified restorable.

## Phase D — Verification (dojo, adversarial)

Scenarios in `tests/014-tenant-isolation/` — run from *inside* a tenant
machine (fly ssh console) acting as the attacker:

1. `psql $LUNA_DATABASE_URL` → works, sees only own DB's tables, can create/drop freely.
2. Connect string edited to another agent's DB name → `permission denied for database`.
3. Connect string edited to `lunatenants` → connection refused.
4. `SELECT * FROM pg_database` → names visible, nothing else; `\dn` shows only own schemas.
5. HTTP POST to another machine's 6PN address with own trusted-proxy secret → 401/403.
6. Normal operation unharmed: chat works, gateway LLM calls metered, vault
   stores/reads credentials, restart survives.
7. Re-provision an agent → password rotates, machine reconnects, data intact.

## Luna-side ask (shrunk from 007.003)

With enforcement in infrastructure, Luna needs **nothing** for isolation to
hold. 007.003's `LUNA_DB_SCHEMA` implementation is no longer required;
recommend Luna instead add one optional fail-fast: log a clear warning at boot
when `LUNA_DB_SCHEMA` is set (deprecated by host). We'll update the 007.003
recommendation accordingly — a Luna release is *not* a dependency of this plan.

## Risks

- **Render connection limits:** per-DB doesn't change totals, but per-role
  `CONNECTION LIMIT 10` caps a runaway tenant. Luna uses NullPool (transient
  connections) — verify 10 is enough under load, tune if needed.
- **Backups:** Render backs up the whole instance — per-tenant restore means
  restoring the instance copy and extracting one DB. Document the runbook.
- **Provision latency:** CREATE DATABASE adds ~1–2s — negligible vs Fly boot.
- **Password in machine env:** Fly machine config is readable via Fly API
  (control plane scope). Same exposure class as today's env secrets; the
  credential is now worthless outside that agent's own DB.

## Out of scope (future hardening)

- Per-tenant Fly apps (network-level isolation instead of shared 6PN) — the
  per-agent proxy secret mitigates the realistic attack; full app-per-tenant
  is an ops project for when paying customers arrive.
- Egress controls on tenant machines (they can reach the internet freely —
  that's a feature for now).
- Postgres row-level security — superseded by per-database model.
