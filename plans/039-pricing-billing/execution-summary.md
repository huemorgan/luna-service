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

## Phase 002 — Pricing versions, assignments, and admin (2026-07-14)

### What was done

- **Version workflow** (`cloud/billing/versions.py` additions): clone →
  draft → edit (re-validate + re-hash on every save) → publish → retire.
  Published versions are immutable forever; retire is idempotent and refuses
  drafts; a flat-path `config_diff` compares any two versions. Publish
  rejects any enabled, non-deprecated gateway model that is in neither tier
  list; `GatewayModel` edits can never touch a published config hash — they
  only gate future publishes.
- **Validation hardening**: explicit `top_tier_models`/`mid_tier_models`
  (model in both or neither is rejected), formula whitelist +
  per-formula constant requirements, top-ups can carry no bonus/gift/interval,
  yearly products must decompose into exactly 12 monthly lots that close to
  the totals, `hosting.price_credits` must equal the `hosting_month` SKU
  constant.
- **Assignments and rollouts** (`cloud/billing/assignments.py`): gapless,
  append-only per-account assignment chain (service check + migration 0003's
  `excl_cpa_no_overlap` gist exclusion constraint as DB backstop);
  `assign_new_account` idempotent; rollouts with
  `new_accounts`/`selected_accounts`/`all_accounts` audiences run as durable
  `billing_outbox` jobs and are restart-idempotent via
  `audit_ref="rollout:{id}"`; default version = newest effective
  new/all-accounts rollout, else highest published.
- **Signup hook** (`cloud/api/auth_routes.py`): account creation assigns the
  default pricing version in the same transaction; unseeded billing degrades
  to a logged warning, never a failed signup.
- **Admin API** (`cloud/api/billing_admin_routes.py`, `/api/admin/pricing`):
  versions CRUD/clone/publish/retire/diff, overview counters (liability,
  uncovered debt, dead jobs, reconciliation holds), manual assignments,
  rollouts, provider-cost versions with rational rates. All mutations require
  a non-blank reason and write audit rows with before/after state; the whole
  router sits behind the new `enforce_same_origin` CSRF dependency
  (Origin, else Referer, vs `base_url`; absent headers pass so non-browser
  clients work).
- **Admin UI** (`cloud/ui/src/pages/admin/pricing/`): collapsible Pricing nav
  group with Overview, Versions (+ rollout form), version detail (raw
  validated JSON editor, diff table, reason-gated publish/retire), LLM &
  services (tier lists, LLM constants, SKU catalog, provider costs), and
  Credit buckets (trial, migration gift, products with Stripe placeholders).
  Structured editors share a `useTargetVersion` hook: newest draft is
  editable, else newest published renders read-only with clone-to-edit.
- **Tests**: 69 new/updated — `test_billing_version_workflow.py` (15),
  `test_billing_assignments.py` (18, incl. signup hook + worker E2E),
  `test_billing_admin_api.py` (14, incl. CSRF matrix),
  `test_billing_versions.py` (14, two phase-001 tests updated for the
  stricter validation), `test_billing_migrations.py` (8 vs real Postgres,
  incl. exclusion-constraint rejection). Full regression: 359 passed,
  1 pre-existing skip.
- **Dojo**: no Playwright MCP browser was available, so
  `tests/039-pricing/dojo_admin_ui.py` is the scripted substitute — dedicated
  Postgres DB, real uvicorn app with the billing worker on, minted session
  cookie, headless chromium. 9/9 scenarios passed (SCENARIOS.md), including
  the full clone → edit → invalid-config rejection → publish → rollout →
  worker applies → default flips loop. Evidence:
  `tests/039-pricing/results/2026-07-14-local/`.

### What was learned

1. **Tightening validation is a cross-phase API change.** Two phase-001
   tests encoded the older, permissive config rules and broke; the fix was
   updating the tests, but the lesson is to grep prior phases' tests whenever
   a shared validator gets stricter.
2. **Never anchor fixed test datetimes at or after the real clock.**
   `assign_version` updates the account cache only when `effective_at <=
   utcnow()`, and the worker's due-check compares wall clock — a "today noon
   UTC" test constant was in the future when the suite ran in the morning.
   Anchor test time constants safely in the past.
3. **Route modules that bind `get_db_session` at import time need a
   per-module conftest patch** — patching `cloud.db.session.get_session`
   alone misses the already-imported binding.
4. **Publish-time tier coverage cannot protect the runtime.** A gateway model
   enabled after publish is unpriced under the active version by design; the
   gateway must fail closed `sku_unpriced` per request (moved to 004, with
   the deferred "calls in flight keep both snapshotted versions" test).
5. **Origin-based CSRF composes cleanly with cookie auth**: same-origin and
   headerless requests pass, cross-origin Origin *or* Referer is rejected —
   and it must never be attached to machine-to-machine routes (webhooks,
   gateway) whose auth is a token or signature.
6. **`verbatimModuleSyntax` is on in the UI build** — interfaces must be
   imported with `import type`, and a file containing JSX must be `.tsx`
   (the shared `api` module became `api.tsx` for `StatusPill`).
7. **The dojo-by-script pattern works end to end** (minted `luna_session`
   cookie + dedicated migrated PG database + headless Playwright) and proved
   a real full loop: UI → CSRF-checked admin API → `billing_outbox` → worker
   → default-version flip. Reusable for 008's customer dashboard scenarios.
8. **A `new_accounts` rollout legitimately completes with `applied=0`** — it
   only moves the default pointer. Operator docs/UI copy should say so, or
   the zero looks like a failure.

### Reassessment of future phases

All seven remaining phase plans amended with dated sections
("Amendments from phase 002 (2026-07-14)"):

- **003**: interval-based snapshotting means no Luna-side work for rollouts,
  but the E2E canary should include a version flip; `sku_unpriced` is an
  expected runtime state during model rollouts.
- **004**: rate against the assignment interval covering call start (cached
  pointer is an optimization); runtime fail-closed for post-publish models;
  provider costs global + effective-dated with rational rates; never attach
  `enforce_same_origin` to tenant/gateway routes.
- **005**: signup hook exists — add the trial gift into it, reading amounts
  from `config.trial`/`config.migration_gift` of the assigned version; reuse
  the handler-registry + `audit_ref` idempotency pattern for renewals.
- **007**: reuse reason + audit + same-origin conventions (webhooks excluded —
  signature auth only); product/lot math must reproduce 002 validation from
  the buyer's assigned version; honor rollout renewal-migration intents at
  invoice time.
- **008**: reuse the dojo harness; `import type`/`.tsx`/`apiError` UI
  conventions; customer mutation routes get `enforce_same_origin`.
- **009**: extend the existing overview endpoint/page for ops; simulator
  candidates are 002 drafts by `config_hash`, cost bases are 002
  provider-cost versions.
- **010**: rollout engine done and browser-verified — migration is a rollout
  plus gifts; `migration_gift` is publish-configurable in the UI; Alembic
  head is now 0003 (needs `btree_gist`, prod role must be able to create
  extensions).
