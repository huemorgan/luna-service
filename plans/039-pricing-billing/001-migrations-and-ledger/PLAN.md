# 039/001 — Migrations, immutable pricing schema, and credit ledger

**Parent:** `plans/039-pricing-billing/PLAN.md` (Phase A)
**Depends on:** nothing — first phase
**Branch:** one reviewable branch/PR per `skills/devprocess/SKILL.md`

## Objective

Introduce real migration tooling and build the financial core: pricing version tables,
billing accounts, grant lots, the double-entry credit ledger, holds, limits, and the
atomic authorize/settle/release service. No production cost path is debited in this
phase.

## Deliverables

### Migration tooling

- Treat production as a pre-Alembic database. Add a hand-verified baseline migration for
  the complete existing schema. Fresh databases run baseline → head; existing production
  is stamped at baseline only after a schema-fingerprint check confirms it matches.
  Subsequent revisions add the billing schema.
- Deploy runs migrations before application startup. All control-plane startup DDL is
  then removed: `Base.metadata.create_all()` (currently `cloud/main.py:57`) and the
  lifespan `ALTER TABLE` loop. The app role needs no DDL privileges.
- Migration test: a fresh empty DB and a production-shaped pre-Alembic backup reach an
  identical schema.

### Durable worker framework

`processed_webhooks` and `billing_outbox` tables alone are not a worker. This phase
delivers the durable billing worker that 005/007/009 build on: leased jobs claimed with
`FOR UPDATE SKIP LOCKED`, heartbeats, bounded exponential retry, dead-letter state,
idempotent handlers. Existing in-process lifespan loops (`cloud/main.py` relay
forwarder/reconciler pattern) are not sufficient for financial work — a crash or deploy
must never lose a paid job.

### Schema

Create per the parent plan's entity list:

- `commercial_pricing_versions`, `commercial_pricing_assignments`,
  `commercial_pricing_rollouts`;
- `provider_cost_versions`, `provider_cost_rates`;
- `billing_accounts`, `credit_grants`, `credit_ledger_transactions`,
  `credit_ledger_postings`, `credit_consumptions`, `account_balance_projections`;
- `billing_holds`, `agent_credit_limits`, `agent_limit_periods`, `agent_hosting_periods`;
- `billable_events`, `rated_charges`, `resource_allocations`, `usage_rollups`;
- `processed_webhooks`, `billing_outbox`, `pricing_simulations`.

Database constraints/triggers:

- balanced postings (sum of zero per posted transaction) — enforced with a deferred
  constraint trigger or an atomic posting protocol, since a normal row trigger rejects
  the temporarily unbalanced state during multi-row inserts;
- immutable published versions and posted transactions (no update/delete); a
  published → retired transition preserves all financial fields;
- nonnegative grant remainder, valid expiration windows;
- unique idempotency keys throughout — every financial mutation stores an operation ID
  and a canonical request hash: same ID + same hash returns the original result, same ID
  + different hash is rejected;
- financial FKs prevent hard deletion of accounts and agents — attribution history can
  never be erased.

Chart of accounts (resolves review M8): `customer_wallet`, `grant_issuance:{source}`,
`credits_consumed`, `uncovered_debt`, `credits_expired`, `manual_adjustment`.
Luna-absorbed provider cost and GAAP revenue are not credit-ledger accounts — they live
on rated charges and reports. A charge posts `-credits` to `customer_wallet`, with the
grant-backed amount credited to `credits_consumed` and any uncovered amount to
`uncovered_debt`. A later grant posts once to the wallet; debt repayment reallocates the
new grant to prior uncovered consumptions and transfers `uncovered_debt →
credits_consumed` without a second wallet movement.

### Rating and version core

- Integer-only rating helpers: micro-USD arithmetic, `1 credit = 10,000 micro-USD`,
  single final `ceil` per logical call. No `float` in any financial path.
- Validated version `config_json` (schema version + hash) including the dynamic SKU
  catalog: SKU key, service, formula type, constants, enabled state.
- Seed commercial version 1 with the parent plan's defaults: trial gift 1,800 / Hobby 19
  / Recurring 100 / Recurring 200 / yearly variants / top-ups; agent-direct-forge LLM
  constants with top/mid model tier lists; hosting 999; non-LLM SKUs seeded disabled.
- Seed provider-cost version 1 from a reviewed, reproducible rate file checked into the
  repo (provider, model, dimension, micro-USD rate, source URL, retrieved date) — never
  from the mutable `GatewayModel.input_cost/output_cost` floats, which are catalog
  metadata and are ignored by all billing paths.

### Ledger operations

- Balanced transaction posting: grant, charge, expiration, refund, reversal, adjustment,
  debt repayment.
- Grant lots with burn order (bonus → gifts/free by earliest expiry → paid recurring by
  earliest expiry → non-expiring top-ups oldest first).
- Projection replay: `account_balance_projections` rebuildable from ledger + consumptions
  with sequence checks for stale writes.
- Atomic `authorize/settle/release` with row locks: posted-balance check, open exposure,
  one bounded uncovered overrun (default cap 1,000 estimated credits), Luna daily/monthly
  limit counters.
- Owner/admin authorization helpers.
- `CLOUD_BILLING_MODE=off|observe|shadow|enforce` config.

## Tests first (scenario tests before implementation)

- Fresh empty DB and production-shaped pre-Alembic DB reach identical schema; app
  startup performs no DDL.
- Postings balance; posted rows cannot mutate; published versions immutable.
- Duplicate idempotency key returns the original result; same key with a different
  payload is rejected.
- Commit/crash between transaction header and postings can never expose partial money.
- Grant into debt allocates to prior uncovered charges without double-moving the wallet.
- Account/agent deletion cannot erase ledger history.
- Worker framework: crash mid-job → lease expires → another worker completes it exactly
  once; poisoned job reaches dead-letter state visibly.
- Concurrent grants/charges/holds preserve a replayable balance (real Postgres
  concurrency tests, not SQLite).
- `5 credits → charge 10 → -5` posts fully; next action blocked.
- One bounded overrun may start; concurrent uncovered overrun is blocked.
- Burn order and every expiration policy exact; yearly scheduled lots activate at their
  effective time.
- Reversal restores the correct economic source without editing history.
- Projection equals full ledger replay after arbitrary operation interleavings.

## Exit criteria

- Admin/test code can create grants, authorize, settle, expire, reverse, and replay.
- Version 1 (commercial + provider-cost) is seeded and immutable once published.
- Migrations run cleanly against a production-shaped backup.
- No production cost path debits anything yet.
