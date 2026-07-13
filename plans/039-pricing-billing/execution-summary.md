# 039 Pricing & Billing — Execution Summary

Running log: one section per executed phase, dated, with what was done and
what was learned. After each phase the remaining phase PLAN.md files are
reassessed and amended from these learnings.

---

## Phase 001 — Migrations and Ledger (2026-07-13)

Commit: `713a621` on `pricing`.

### What was done

- **`cloud/billing/` package** (new):
  - `money.py` — integer-only arithmetic. 1 credit = $0.01 = 10,000 micro-USD.
    Provider rates carried as exact rationals (numerator, denominator);
    `rate_logical_call_credits()` sums rational vendor parts, adds one margin,
    and applies exactly one final ceil. Bools rejected as money.
  - `models.py` — all 21 billing tables on the shared `Base` (pricing
    versions/assignments/rollouts, provider cost versions/rates, billing
    accounts, grants, ledger transactions + postings, consumptions, balance
    projections, holds, agent limits + periods, hosting periods, billable
    events, rated charges, resource allocations, usage rollups, processed
    webhooks, `billing_outbox` jobs, pricing simulations). All financial FKs
    `ondelete=RESTRICT`. Ledger `seq` is `BigInteger().with_variant(Integer,
    "sqlite")` so SQLite tests get autoincrement and Postgres gets BIGSERIAL.
  - `ledger.py` — double-entry core. Balanced postings enforced in code
    (`UnbalancedPostings`); grant/charge/expiration/debt-repayment/reversal
    posting conventions; burn order bonus → gift/free → paid → topup, then
    earliest expiry (NULLS LAST); charges post fully even into debt
    (5 → charge 10 → −5); new grants repay debt with no second wallet
    movement; scheduled lots post only at activation; holds with a single
    bounded uncovered overrun (cap default 1,000); stale holds become
    `needs_reconciliation` and still count as exposure; agent daily/monthly
    UTC-calendar limits with authorization-time exposure and settle-time
    settlement; projection rebuild with `last_seq` stale-write guard.
  - `worker.py` — durable outbox: enqueue-in-caller's-txn, claim with
    FOR UPDATE SKIP LOCKED (Postgres only), leases + heartbeats, bounded
    exponential backoff (30s·2ⁿ capped 4h), dead-letter at max_attempts.
  - `versions.py` — commercial config schema v1 validation (floats rejected
    recursively, credit value fixed at 10,000, subscription invariant
    `paid_credits == price_usd_cents`, dup key checks), canonical sha256
    config hash, draft → publish lifecycle with tamper check; published
    versions immutable.
  - `provider_rates_v1.py` + `seed.py` — launch defaults: trial 1,800/28d
    (75/day, 800/month, 1 active Luna), migration gift = trial treatment,
    hosting 999, hobby/recurring/yearly/topup products, only `llm_call` and
    `hosting_month` SKUs enabled (everything else fails closed), provider
    cost v1 rates as exact rationals with source URLs.
- **Alembic** (new): `0001` baseline = the 15 pre-billing core tables;
  `0002` = the 21 billing tables **plus Postgres-only triggers**: postings
  must sum to zero per transaction at COMMIT (deferred constraint trigger,
  also rejects posting-less headers), UPDATE/DELETE forbidden on posted
  ledger rows, DELETE forbidden on grants/consumptions/billable
  events/rated charges, published pricing/provider versions immutable except
  published → retired, rates of published cost versions frozen.
- **`cloud/db/migrate.py`** (new deploy entrypoint): alembic_version present
  → upgrade head; empty DB → upgrade head; pre-Alembic production shape →
  fingerprint core tables/columns (existence only, extra columns tolerated
  with a warning), stamp 0001, upgrade head; unknown schema → exit 1 with no
  writes.
- **`cloud/main.py`** — the entire startup-DDL block (create_all + ad-hoc
  ALTERs + one-time backfills) removed; lifespan now only seeds services,
  models, and the owner admin bit. **`cloud/Dockerfile`** CMD runs
  `python -m cloud.db.migrate && uvicorn …` so a failed migration aborts the
  deploy while the old instance keeps serving.
- **Tests** — 63 new billing tests: `test_billing_money.py` (unit identity,
  single-ceil, margin-once), `test_billing_ledger.py` (26: balanced/idempotent
  postings, burn order, debt round-trip, expiration boundary, scheduled lots,
  reversals, projection replay, overrun rules, agent limits, stale holds),
  `test_billing_worker.py` (lease reclaim exactly-once, retry → dead-letter),
  `test_billing_versions.py` (validation, hash, publish, seeds),
  `test_billing_migrations.py` (Postgres-only, auto-skipped without
  localhost:5435: fresh vs stamped paths produce byte-identical schemas,
  fingerprint refusal, triggers verified end-to-end). Full suite: **311
  passed, 1 skipped** — no regressions from removing the startup DDL.

### What was learned

1. **Tests caught two real worker bugs**: `backoff_for_attempt` overflowed C
   int at large attempt counts (exponent now clamped), and
   `run_claimed_job` accessed an expired ORM instance after rollback
   (job id now captured before the handler runs).
2. **SQLite returns naive datetimes; Postgres returns aware.** Any
   in-Python comparison against `now` must normalize (`_aware()` in
   ledger.py). SQL-side comparisons are unaffected. Every later phase doing
   Python-side timestamp logic (renewals, anchors, dunning timers) must use
   the same normalizer or compare in SQL.
3. **The single-bounded-overrun design means "exposure counted" ≠ "authorize
   blocked"** — a hold that exceeds availability is *allowed* once within
   cap. Tests (and later the gateway UX in 004) must distinguish
   `credits_exhausted` (balance ≤ 0) from `exposure_limit`.
4. **`alembic/env.py` prefers `CLOUD_DATABASE_URL` over the programmatic
   config URL.** Anything invoking Alembic against a non-default DB (tests,
   ops scripts, the 010 prod stamping) must set the env var, not just
   `Config.set_main_option`.
5. Deferred constraint triggers work cleanly for the balanced-postings
   invariant on Postgres — the temporarily unbalanced state during a
   multi-row insert never fires it, and posting-less headers are caught at
   commit. SQLite runs rely on the identical service-layer check.
6. Grant `source_type` is check-constrained to real sources
   (`subscription_paid`, `subscription_bonus`, `topup`, `free_recurring`,
   `gift`, `refund`, `admin`) — it is *not* the visible category. Phase 005
   and 007 grant-creation code must map explicitly.
7. Autogenerate-then-freeze worked well: scratch DB + `CLOUD_ALEMBIC_SCOPE=core`
   filter produced a faithful 0001; hand-verification plus the
   identical-schema test (fresh vs stamped) gives high confidence for the
   production stamping in 010.

### Reassessment of future phases

- **002 (pricing versions + admin):** validation/hash/publish primitives and
  the seeded v1 already exist — 002 becomes admin API + UI over
  `cloud/billing/versions.py`, not new domain logic. Amended.
- **003 (Luna core metering):** unchanged in scope; noted that billing
  records must carry `root_action_id`/logical-call ids that match the ledger
  idempotency scheme (`operation_id` + canonical hash) already fixed here.
- **004 (gateway metering/enforcement):** must surface distinct
  `credits_exhausted` vs `exposure_limit` vs `luna_daily_limit`/
  `luna_monthly_limit` error codes — the ledger already emits them. Amended.
- **005 (grants/hosting/limits):** debt repayment, scheduled lots, and limit
  periods are already implemented in 001's ledger — 005 wires products and
  renewal jobs onto them (via `billing_outbox` handlers). Source-type
  mapping note added. Amended.
- **007 (Stripe):** reversal of a partially consumed grant intentionally
  errors, pointing to 007's clawback flow — that flow must handle it.
  Noted in 007.
- **010 (rollout/migration):** prod stamping procedure confirmed feasible;
  `CLOUD_DATABASE_URL` env requirement and the known `users.is_admin`
  nullability drift (tolerated by the fingerprint) recorded there.
