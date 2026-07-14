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

## Phase 004 — Gateway metering and enforcement (2026-07-14)

Note: phase 003 (Luna core metering) is deferred — the Luna repo is mid-flight
on branch 037, and 3.3 depends on the block contract this phase freezes. 004
has no dependency on 003, so it ran first.

### What was done

- **`cloud/gateway/route_catalog.py`** (new) — deny-by-default route
  classification: an explicit `(service, METHOD, path)` table maps each
  gateway route to `metered` (with SKU + adapter) or `free`; `*` matches
  exactly one path segment. Anything not in the table is `unknown` and fails
  closed as `sku_unpriced` in enforce mode.
- **`cloud/gateway/adapters.py`** (new) — per-provider usage collectors that
  observe response bytes as they stream through the proxy: Anthropic JSON +
  SSE (usage frames may be split across wire chunks and repeated —
  values are **max-merged** per dimension, including nested
  `cache_creation`), OpenAI JSON + SSE (`cached_tokens` subtracted from
  input), with a scan cap for oversized non-LLM bodies (embeddings). Also
  `prepare_managed_body` (injects `stream_options.include_usage` where the
  provider needs it) and pre-flight dimension estimation for hold sizing.
- **`cloud/billing/rating.py`** (new) — snapshotted version resolution
  (commercial version from the account's assignment-interval chain at call
  start; provider-cost version = newest published effective at call start;
  immutable published configs cached per version id) and credit math:
  exact rational vendor parts per attempt, failed attempts Luna-absorbed,
  exactly one margin and one final ceil per logical call
  (`rate_logical_call_credits`). Unrated dimensions are recorded in the rule
  snapshot, never guessed.
- **`cloud/gateway/enforcement.py`** (new) — the mode matrix around each
  managed call. `prepare()`: attribution from the authenticated token only,
  route classification, version snapshots, unpriced fail-closed, hosting
  `payment_due` check, hold estimate; enforce authorizes a real hold,
  shadow runs the same authorize inside a rolled-back savepoint
  (`begin_nested()`) and records `would_block`, observe records only, off
  bypasses. `finalize()`: one BillableEvent per provider attempt
  (idempotency `{operation_id}:{attempt_number}`), one RatedCharge per
  logical call with a full rule snapshot; enforce enqueues a durable
  `gateway_finalize` outbox job (settle or release); a 2xx with no parseable
  usage (`usage_missing`) marks the charge `needs_reconciliation` and leaves
  the hold for the reaper — never a silent release. `stale_hold_reaper_loop`
  (60 s) is the backstop that moves expired holds to `needs_reconciliation`.
- **Block contract frozen** (what 003's Luna-side UX will consume): 402 with
  `{error: {type: "billing_blocked", code, message, retryable}}`; codes
  `credits_exhausted`, `luna_daily_limit`, `luna_monthly_limit`,
  `hosting_payment_due`, `sku_unpriced`, `exposure_limit`,
  `billing_temporarily_unavailable` (last two retryable). Fails closed
  **only** in enforce mode; observe/shadow never affect the customer even if
  the billing store is down.
- **`cloud/api/gateway_proxy.py`** — billing woven around the existing
  managed flow: pre-flight `prepare` (blocks before any provider contact),
  `x-luna-*` headers stripped from upstream requests, shared
  `billing_attempts` across fallback retries (failed attempts recorded
  non-billable so one logical call gets exactly one margin), streaming
  finalize in the response generator's `finally` under `asyncio.shield`,
  502-path finalize releases the hold. BYOK is never billed.
- **`cloud/main.py`** — the stale-hold reaper now actually runs: it shares
  the billing-worker advisory lock via `asyncio.gather` in the lifespan.
- **Tests** — `cloud/tests/test_gateway_billing.py`, 40 new (unit: route
  table, adapters incl. chunk-split/duplicate-frame SSE, rating single-ceil
  and absorption; integration over a mocked Anthropic upstream: full mode
  matrix, settle-via-worker balance 100 → 96, unspoofable attribution +
  header stripping, alias → canonical tier, daily-limit and payment-due and
  exposure-limit blocks, billing-store failure open in observe / closed in
  enforce, usage_missing + reaper backstop, upstream connect-error hold
  release, fallback single-margin, BYOK bypass, no prompts/outputs/keys in
  billing rows). Full regression: **399 passed, 1 pre-existing skip**
  (359 + 40).
- **Dojo** — `tests/039-pricing/dojo_gateway_billing.py`: scratch Postgres
  `dojo039gw`, real uvicorn booted per mode, mock Anthropic upstream on a
  real port serving JSON + chunked SSE, live 5 s outbox worker. 9/9
  scenarios passed (SCENARIOS.md §039/004), including a real worker
  settlement and every hold terminal. Evidence:
  `tests/039-pricing/results/2026-07-14-local/REPORT-gateway.txt`.

### What was learned

1. **Shadow mode = rolled-back savepoint, not a shadow wallet.** Running the
   real `ledger.authorize` inside `begin_nested()` and rolling it back gives
   byte-identical decision logic to enforce with zero balance effect and no
   parallel bookkeeping. The PG dojo proved savepoints behave identically to
   the SQLite tests. This is a deviation from the plan's sketch (isolated
   shadow ledger) — simpler and strictly more faithful.
2. **ORM column names must be checked, not assumed**: the only real
   implementation bug found by the tests was `version.config` vs the actual
   column `config_json`. Cheap habit: open `cloud/billing/models.py` before
   writing accessors.
3. **The aiosqlite `:memory:` StaticPool is a single shared connection** —
   a fire-and-forget task (`_mark_key_used_bg`) opening its own session
   interleaves transactions with a concurrent finalize and silently clobbers
   commits (~80 % flake, no error). Production Postgres is unaffected
   (separate pooled connections; the live dojo confirmed). Fix: autouse
   fixture patches the background task to a no-op, documented as a
   test-environment artifact. **Rule for later phases: any test asserting on
   rows written concurrently with a background task must neutralize that
   task under SQLite.**
4. **`stale_hold_reaper_loop` existed but nothing started it** — writing the
   dojo (which watches holds reach terminal states) exposed that main.py
   never ran the reaper. Lesson: every background loop needs a startup-wiring
   test or a dojo scenario that would fail without it; 005's renewal loops
   get the same scrutiny.
5. **`usage_missing` must not settle**: a 2xx with unparseable usage settles
   at the estimate only via *reconciliation*, never automatically — the hold
   is deliberately left for the reaper so the gap is always visible. Rated
   charges carry `cost_source="estimated"` for this case.
6. **SSE usage frames arrive split and duplicated on the real wire** — the
   40-byte-chunk dojo scenario validated the max-merge design; a last-frame-
   wins or sum-merge adapter would misbill.
7. **Wall-clock vs frozen-clock mismatches bite in both directions**:
   a reaper test set `expires_at` from the suite's fixed NOW while
   `mark_stale_holds` compares real time. Timestamps that SQL compares
   against `now()` must be derived from real wall clock in tests.
8. **Dojo-as-live-network-script** is the right shape for proxy-plane
   phases: no browser UI exists, but booting the real app per mode against
   scratch Postgres with a mock upstream on a real socket caught what
   in-process tests can't (worker settlement timing, PG savepoints, on-wire
   chunking). Scenario 8 needed a settle-poll (the 5 s worker is genuinely
   async) — assert on *terminal states with a timeout*, not immediacy.

### Reassessment of future phases

All remaining phase plans amended with dated sections
("Amendments from phase 004 (2026-07-14)"):

- **003 (deferred, runs later)**: the block contract above is now frozen —
  Luna core consumes it verbatim; 402 handling can be built against the dojo
  mock. Interval-snapshotting confirmed working under load.
- **005**: new non-LLM gateway services must ship a `route_catalog` entry +
  adapter or they 402 `sku_unpriced` in enforce (deny-by-default is live);
  renewal/expiry loops follow the reaper pattern and must be wired in
  main.py's lifespan with a dojo scenario proving they run; hosting
  `payment_due` is already enforced at the gateway — 005 sets/clears the
  flag; SQLite background-task rule applies to renewal tests.
- **006**: no scope changes (noted in the plan for the record).
- **007**: `needs_reconciliation` charges from `usage_missing` are a queue
  Stripe-era ops must drain; dunning sets `payment_due`, the gateway already
  blocks on it (no new enforcement code).
- **008**: customer-visible usage reads `rated_charges` + rule snapshots —
  snapshot fields (context/tier/sku/margin/models/status) are now stable;
  never expose context/tier/margin fields themselves, only credits.
- **009**: the simulator replays `billable_events` through `rating.rate_call`
  under candidate configs — the AttemptFacts shape is now the stable replay
  input; ops page gets counters for `needs_reconciliation` charges and
  stale-hold reaper activity.
- **010**: enforce rollout = flip `CLOUD_BILLING_MODE` env per stage
  (off → observe → shadow → enforce), each stage verified with the 004 dojo
  run against staging; the mode matrix is already tested so the runbook is
  configuration, not code.

## Phase 005 — Grants, hosting lifecycle, and limits (2026-07-14)

Branch `pricing`. Full regression: 429 passed, 1 skipped (was 399+1 after
004). Dojo: 11/11 scenarios (`tests/039-pricing/dojo_hosting_lifecycle.py`,
SCENARIOS.md §039/005).

### What was done

- **Grants** (`cloud/billing/grants.py`): `grant_trial_gift` — 1800 credits,
  28-day expiry, idempotent via `source_key trial:{account_id}`, wired into
  the signup transaction (`_upsert_user_and_account`); `grant_admin_gift`;
  trial detection = no grant with a paid source type
  (`subscription_paid` / `subscription_bonus` / `topup`); trial→paid flip is
  therefore automatic on first top-up. All amounts from the published
  pricing config (`config.trial`), never constants.
- **Per-Luna limits**: `apply_trial_agent_limits` writes 75/day, 800/month
  rows insert-only (never overwrites an admin's manual override).
- **Hosting lifecycle** (`cloud/billing/hosting.py`): monthly 999-credit
  periods (`hosting_month` SKU). Create (enforce) = explicit
  `posted_balance` check → 999 hold (`count_toward_limits=False`, 30-min
  TTL) → durable `hostprov` outbox job → hold settled and period activated
  on confirmed provisioning. Renewal sweep in the maintenance loop:
  monthly-anchor clamp (`add_month_clamped`, anchor = day of first period),
  seamless `starts_at = old.ends_at`, idempotent charge key
  `hosting_renew:{old.id}`. Unpayable renewal → `payment_due` + durable
  `hostsusp` suspend job; recovery ONLY via the start endpoint
  (`try_recover_payment_due`: fresh month charged, key
  `hosting_recover:{period.id}`). Observe/shadow write lifecycle rows with
  zero money movement; `off` keeps the legacy asyncio provisioning path.
- **Route guards** (`cloud/api/agent_routes.py`): create = trial cap (402
  `active_luna_limit`) + balance check (402 `credits_exhausted`, no rows on
  refusal); start = `hosting_blocked` → recovery-or-402
  `hosting_payment_due`; retry = durable job requeue (attempts reset);
  destroy rewritten as soft delete — `deleted_at` tombstone, period ended,
  durable `agent_teardown` job, billing rows and attribution kept forever;
  all ownership queries filter `deleted_at IS NULL`. Proxy wake
  (`_try_wake_agent`) refuses `payment_due` Lunas in enforce — traffic can't
  bypass the explicit paid restart.
- **Admin gifts** (`cloud/api/billing_admin_routes.py`): POST
  `/api/admin/pricing/gifts` — reason-gated (400 without), default expiry
  from `gift_default_days`, idempotency-key dedupe, audit row
  `pricing.gift.create`.
- **Migration 0004**: `agents.deleted_at`; billing FKs stay RESTRICT.
  `migrate.py` gained `POST_BASELINE_COLUMNS` (see learnings).
- **Tests**: `cloud/tests/test_billing_hosting.py` — 30 tests (clamp math
  incl. leap/year-wrap, trial gift/flip/limits, hold+job idempotency,
  settle/reap/missing-hold matrix, renewal clamp + payment_due + recovery,
  soft delete, teardown handler, wake guard, admin gifts). Migration tests
  updated: dynamic head revision, 0004 column assert.
- **Dojo** — `tests/039-pricing/dojo_hosting_lifecycle.py`: scratch PG
  `dojo039host`, real app in enforce then observe, live maintenance loop
  renewing seeded past-due periods, real 401s from Fly (invalid token) for
  the failure paths, REAL signup transaction for the trial gift. 11/11.
  Evidence: `tests/039-pricing/results/2026-07-14-local/REPORT-hosting.txt`.

### What was learned

1. **`ledger.settle` deliberately accepts `needs_reconciliation` holds** —
   a reaped (expired) provision hold still settles normally with a posted
   charge once provisioning confirms. The provision handler's
   try/except around settle exists for the OTHER cases: hold never existed
   (mode flipped observe→enforce between creation and handler run) or
   terminal (released/expired). In those cases the period still activates —
   the customer has the machine — with `charge_transaction_id = NULL`,
   logged for ops. Retrying the job would never make the settle succeed.
2. **The pre-Alembic fingerprint must compare against the 0001 BASELINE
   shape, not head ORM models.** 0004 adding `agents.deleted_at` made
   `migrate.py` refuse every legacy database ("missing columns:
   deleted_at"). Fix: `POST_BASELINE_COLUMNS` exclusion map in migrate.py —
   it must grow with every future migration that touches a CORE_TABLES
   table. The migration test suite now asserts against the dynamic head
   revision (`ScriptDirectory.get_current_head()`) instead of a hardcoded
   string — the hardcode broke at 0003→0004 and would have broken every
   phase after.
3. **SQLite identity-map staleness**: with `expire_on_commit=False`, after
   a route commits in its own session, `db_session.get()` in the test
   returns cached objects — `await db_session.refresh(obj)` before
   asserting on route-mutated rows.
4. **`start_agent` constructs the runtime outside its try/except** — a
   missing `FLY_API_TOKEN` 500s the request and rolls back the recovery
   charge committed later in the same session. The dojo therefore uses a
   present-but-bogus token (Fly answers 401 inside the try/except). Worth a
   hardening pass someday: move `_get_runtime()` inside the guarded block
   so an env misconfiguration can't turn a billing-committed restart into
   a rollback.
5. **Time-travel seeding beats clock mocking for live-loop dojos**: seed
   past-due periods BEFORE boot and let the maintenance loop's immediate
   first tick act on them. But pick dates so exactly ONE renewal lands in
   the future — a period several months overdue chains one renewal per 60 s
   sweep until the wallet empties, changing the state mid-run.
6. **Recovery-vs-sweep separation confirmed in code**: `renew_due_periods`
   only touches `state='active'` rows, so `payment_due` periods are never
   auto-charged by the sweep even after the account is refunded — restart
   is always an explicit, user-visible action. The charge keys differ
   (`hosting_renew:{old.id}` vs `hosting_recover:{period.id}`) and the
   posted-balance check prevents any double-charge overlap.
7. **The signup allowlist blocks stub-identity dojos** — for end-to-end
   signup coverage, call the real `_upsert_user_and_account` in-process
   against the dojo database instead of faking an OAuth round-trip.

### Reassessment of future phases

All remaining phase plans amended with dated sections
("Amendments from phase 005 (2026-07-14)"):

- **003 (deferred)**: the 402 surface Luna core must handle now includes
  `active_luna_limit` and `hosting_payment_due` alongside
  `credits_exhausted`; per-Luna daily/monthly limits (75/800 trial) are
  live rows Luna core's snapshotting already respects.
- **006**: trial→paid flip is automatic on the first paid grant
  (source-type driven) — Stripe setup needs no account-state migration,
  only correct `source_type` on checkout-created grants.
- **007**: top-ups must post grants with `source_type='topup'` (that alone
  flips trial→paid and lifts the 1-Luna cap); dunning writes `payment_due`
  via the existing hosting flag — the gateway, wake path, and start
  endpoint already enforce it; recovery-on-start already charges a fresh
  month, so Stripe dunning needs no restart logic of its own.
- **008**: customer UI shows hosting periods (state, ends_at), the
  payment_due recovery CTA (start = pay), and gift/trial expiries from
  `credit_grants`; soft-deleted Lunas stay out of lists but their charges
  remain in history (attribution is permanent).
- **009**: ops page gets counters for periods stuck `pending`/`payment_due`,
  dead `hostprov`/`hostsusp`/`teardown` jobs, and settle-without-charge
  activations (charge_transaction_id NULL — learning #1); the simulator's
  replay input gains hosting renewals (pure config: price × periods).
- **010**: the migration gift (999 × N running Lunas + 801, 28 days) rides
  the same grant machinery (`source_key migration:{account_id}` pattern,
  insert-only limits); POST_BASELINE_COLUMNS must be checked in the
  rollout runbook whenever prod is stamped; enforce-stage verification now
  includes the hosting dojo alongside the gateway dojo.

## Phase 008 — Customer billing UI (2026-07-14)

Executed out of order (before 006/007 Stripe) per Roy: "i want to see the
packages first - stripe packages i think can be done later." Everything
that needs payments renders as a disabled "Coming soon" button gated on
`payments_enabled` from the API, so 007 only has to flip the flag and wire
the buttons.

### What was done

- **Customer billing API** (`cloud/api/billing_routes.py`): `/api/public/pricing`
  (unauthenticated, published-version-gated, 503 when unpublished) and
  `/api/billing/*` — summary (balance, category split, holds, debt, trial,
  hosting per agent, recovery payload), grants with burn order, products,
  usage summary (range + trend + projected depletion + per-Luna limit
  windows), breakdown by agent/service/plugin/action_type/model/root_action,
  actions grouped by root action (retries counted once, plugin children
  nested) + CSV export, statement with per-row running balance (window SUM
  over posting seq), and owner-only PUT /limits/{agent_id} behind the CSRF
  same-origin guard. Credits only — no margins, micro-USD, tiers, contexts,
  SKUs or vendor costs anywhere in a customer payload (tests grep for the
  tokens).
- **Marketing /pricing rewritten** to be API-driven: trial / Hobby / Pro /
  Power cards, monthly↔yearly toggle (yearly = per-month billed-yearly +
  yearly gift credits), top-ups and always-on hosting cards; the old
  "degrades gracefully" copy removed.
- **Dashboard billing page** (`/dashboard/billing`): trial/exhaustion/
  payment-due banners from the frozen 402 codes (`BLOCK_MESSAGES` maps all
  seven), stat cards, hosting list, credit lots with burn order, package
  cards (Coming soon), usage with range picker + trend bars + per-Luna
  progress and an inline limit editor, breakdown pivots, expandable recent
  actions + CSV link, statement with Load more.
- **AgentDetail Spend card** replaces the Coming-soon placeholder: daily/
  monthly usage vs limits, hosting state, link to the billing page.
  Dashboard header gets a Billing link.
- **Tests**: 17 new API tests (SQLite harness) — 446 passed / 1 skipped
  total, no regressions. Browser dojo `dojo_billing_ui.py` 12/12 on
  Postgres + real uvicorn + Playwright; screenshots 10–17 under
  `tests/039-pricing/results/2026-07-14-local/`. Logs secret-scanned.

### What was learned

- **A `now` older than the grant's `effective_at` silently un-burns lots.**
  The dojo captured `now` before the real signup created the trial grant and
  passed it to `ledger.charge(now=...)`; burnability filters
  `effective_at <= now`, so every charge went to DEBT while the wallet
  moved normally — the page looked right except lots stayed full. Charges
  in seeds should let `charge()` default its own clock.
- **SQLite tests don't prove Postgres arithmetic.** `SUM()` comes back as
  `Decimal` on PG and `int` on SQLite; `Decimal / float` raised a 500 in
  `/usage/summary` that 17 green SQLite tests never saw. The dojo caught
  it. Cast aggregates (`int(...)`) before mixing with floats.
- **The CSRF same-origin guard needs `CLOUD_BASE_URL` in every dojo** that
  drives a browser through a mutation — the browser sends a real Origin
  and the guard compares against settings, not the request host.
- **`asyncio.run()` cannot be called inside `sync_playwright`** (it keeps a
  loop running on the thread); DB assertions from dojo scenarios must run
  the coroutine on a fresh thread.
- **Full-page screenshots capture unrevealed marketing sections** (reveal-
  on-scroll IntersectionObserver); `reduced_motion="reduce"` in the
  Playwright context uses the site's own reduced-motion CSS to show
  everything and keeps screenshots deterministic.
- Playwright `get_by_text` on multi-node JSX was NOT the problem it looked
  like (React renders `{a} / {b}` as one text run); when a locator misses,
  read the aria snapshot before touching the component.

### Addendum — tab split (2026-07-14)

Roy asked for the billing page split into top tabs; shipped same day:
**Status** (stat cards, new "Credit sources" consumption bars, hosting,
credit lots), **Usage** (range stats, trend, breakdown, recent actions,
CSV, limit editor), **Billing** (packages + statement). Tab state lives in
`?tab=` via `useSearchParams`; block/trial banners stay above the tab bar.
The source bars aggregate `/api/billing/grants` by `category` (gift+free
merged as "Gift & trial"). Roy's recalled burn order (bucket → bonus →
top-up) was inverted — the actual order is free → gift → bonus → top-up →
bucket last; the bar hints state the real order. Dojo re-passed 12/12 with
new screenshot 18. Two more Playwright lessons: `locator.count()` doesn't
auto-wait (use `expect(...).to_have_count(n)`), and `get_by_text` needs
`exact=True` when a label is echoed inside hint/note text.

### Addendum — pricing revision (2026-07-14)

Owner decisions applied to the v1 launch config (nothing deployed, so the
seed defaults were edited in place):

- **Tiers are now $19 / $99 / $199.** Credit totals per tier stay at
  1,900 / 11,000 / 25,000 — paid credits track the price (1 cr = 1¢), so
  the bonus absorbs the difference: Pro 9,900 + 1,100, Power
  19,900 + 5,100. Keys renamed `recurring_100/200` → `recurring_99/199`.
- **Yearly gift doubled to two months of paid monthly credits**
  (Hobby 3,800, Pro 19,800, Power 39,800).
- **Strike-through value price** wherever a bonus makes the credit value
  exceed the price: marketing /pricing and the dashboard Billing tab show
  ~~$110~~ $99 and ~~$250~~ $199 (credit total is literally a cent
  amount, so `usd(paid + bonus)` is the struck value).
- 006 Stripe plan's product/price table updated to the new keys and
  yearly totals ($1,188 / $2,388).
- Dojo hardening: transient network stalls on the external Google Fonts
  request hung `page.goto(..., wait_until="load")` for 30s+; all dojo
  navigations now wait on `domcontentloaded` (assertions auto-wait
  anyway).

### Plan reassessment

- **007 (Stripe integration)**: the UI contract is now concrete — flip
  `payments_enabled`, replace the disabled buttons with checkout links, add
  a top-up picker over `topup_steps_usd_cents`, and surface
  `recovery.payment_action_required` / `next_payment_retry_at` in the
  banner. No new pages needed. Amended in the phase file.
- **009 (simulator/operations)**: the customer API's projection
  (`projected_depletion_days`) is a plain range average and labeled an
  estimate; 009's simulator should reuse the same endpoint semantics rather
  than invent a second projection. Noted in the phase file.
- **006 unchanged** (account setup already specced; keys live in
  `.stripe-dev.env`).

## Phase 006 — Stripe account setup (2026-07-14)

### What was done

Executed against Roy's real Stripe account in **test mode** with Roy
present in the browser session (568933c, 93889cc):

- Created the six subscription Products/Prices ($19/$99/$199 monthly,
  $228/$1,188/$2,388 yearly) and the four top-up Prices ($10/$25/$50/$100)
  matching the commercial_v1 catalog exactly.
- Billing Portal configuration: payment-method update and invoice history
  on; **plan switching disabled in the portal** — plan changes are
  code-owned (007) so grants can never originate from a portal action the
  ledger doesn't understand.
- Tax defaults set via API. Still on Roy's side: head-office address,
  business profile/branding/statement descriptor, the restricted API key
  into `.stripe-dev.env`, and the webhook endpoint + signing secret once
  007 deploys.

### What was learned

- Stripe object IDs (`prod_`/`price_`) are identifiers, not secrets — they
  can live in commits and admin UIs; only keys are secret.
- The portal config API is versioned per configuration object; disabling
  `subscription_update` there is what makes "plan changes are code-owned"
  enforceable rather than aspirational.

## Phase 007 — Stripe integration (2026-07-14)

Order amended by Roy: 008 (billing UI) shipped first, so 007 ended as pure
wiring against a finished UI. Executed in six reviewable slices, each with
tests + full-suite regression before push.

### What was done

- **Settings/gateway/tables (ed4846f)** — `CLOUD_STRIPE_*` settings; a
  ~200-line httpx gateway (form-encoding, idempotency keys, livemode
  guard, webhook signature verify) instead of the stripe SDK;
  migration 0005: price bindings, subscription mirror, processed-webhook
  dedupe, payment clawback accumulator. `payments_enabled` is DERIVED:
  settings complete AND every catalog product bound for the declared mode
  — a misconfigured deploy degrades to "Coming soon", never a broken
  button.
- **Checkout/portal (b8a87c4)** — one Stripe Customer per account (row
  lock + idempotency key); checkout only for the FIRST subscription;
  top-ups only from catalog steps; price-drift check blocks checkout
  before money moves; admin bindings API.
- **Webhooks → grants (fac6cca)** — signature-only auth over the raw body
  (no cookies/origin); intake dedupes into `processed_webhooks` and
  enqueues a durable billing job in the same transaction; handlers fetch
  CANONICAL objects from Stripe and never trust payloads. invoice.paid
  runs a strict proof-of-money gate (paid, real PI, usd, one line, pretax
  == catalog price, buyer's catalog). Yearly = 12 monthly paid lots on
  calendar-clamped boundaries + bonus lots + one year-spanning gift lot;
  monthly = paid + bonus; top-ups = no-expiry lot after metadata/amount
  verification.
- **Clawback (03a39fd)** — proportional: target = floor(granted ×
  refunded_pretax / pretax), applied scheduled-lots-first (cancel, no
  postings), then active remainders (reversal postings), then
  reclassifies already-consumed credits as debt (DEBT +x / CONSUMED −x
  with a grant_id-NULL consumption row — the exact inverse of debt
  repayment, so future grants auto-repay it). Disputes accumulate into
  the same per-payment cap; a won dispute restores via a fresh
  `stripe-restore` lot.
- **Dunning (e2bbde9)** — invoice.payment_failed grants nothing, marks
  `billing_status=past_due`, maps PI status to
  `payment_action_required`, stores `next_payment_retry_at`. Recovery is
  not a separate path: the next verified invoice.paid grants once and
  clears the flags. Top-ups keep working while past_due without clearing
  it.
- **Plan changes (b1331c7)** — code-owned subscription updates, never a
  new checkout, never proration. Upgrade: `billing_cycle_anchor=now` +
  `pending_if_incomplete` → full-price invoice now; local state changes
  ONLY from the verified invoice (payment failure = old plan intact).
  Downgrade: price switch with `proration_behavior=none`, nothing charged
  until renewal; `pending_product_key` is UI state cleared by the renewal
  grant.
- **UI wiring (fa5ce6f)** — summary exposes the mirror (subscription
  block, billing_status, real recovery fields); BillingPage plan buttons
  keyed to mirror state, monthly/yearly toggle, top-up picker, portal
  link, past_due banner with retry date; dojo Act II reboots the app with
  Stripe configured (17 scenarios).

Suite grew 462 → 536 passed across the phase.

### What was learned

- **`_post_grant_activation` posts `original_credits`** — cancelling a
  scheduled lot must zero BOTH original and remaining credits or a later
  activation over-grants. Found by reading the ledger, not by a failing
  test; worth a regression test whenever grant lifecycle changes.
- Registering webhook event types before their handlers exist dead-letters
  jobs: keep `HANDLED_EVENTS` trimmed to implemented handlers and grow it
  per slice.
- SQLite returns naive datetimes where Postgres returns aware — an
  `_aware()` helper at every mirror/grant comparison point is cheaper than
  chasing each assertion.
- Yearly-lot tests must straddle "now" (first lot active, rest scheduled);
  calendar clamping (Jan 31 → Feb 28/29) is best pinned in a dedicated
  add_months unit test, not the integration fixture.
- `pending_if_incomplete` + anchor-now is the exact Stripe idiom for
  "upgrade now, but a failed payment must not move the plan"; with grants
  gated on verified invoices, the local mirror needs NO optimistic update.
- The clawback/debt symmetry (clawback of consumed credits == inverse of
  debt repayment) meant zero new ledger account types and free
  auto-repayment from future grants — designing new flows as compositions
  of existing posting shapes keeps the invariant checker authoritative.
- httpx MockTransport with a path→object dict fakes the whole Stripe GET
  surface in ~15 lines; POST recording (parse_qs of the form body) asserts
  outbound payloads without a fake server.
- A dojo can flip a server-side feature flag mid-run by restarting the
  app with different env (bogus-but-well-formed keys) — bindings in DB +
  fake keys exercise every payments-enabled render path with zero Stripe
  traffic, and one deliberate failing call proves the 502 error surface.

### Reassessment of future phases

- **003 (Luna-core metering, luna repo)**: unchanged by 007 — it feeds
  BillableEvents through the gateway; nothing Stripe-specific leaks into
  the agent. Still next after rollout pieces.
- **009 (simulator/operations)**: add operational checks for the new 007
  surfaces — webhook dead-letter monitoring (jobs stuck pending/dead),
  processed_webhooks error states, StripePayment clawback drift vs
  Stripe's refund totals. The simulator should replay canned webhook
  fixtures through `intake_event` + worker rather than mock at the
  handler layer. Noted in the phase file.
- **010 (rollout)**: the deploy checklist gains concrete steps — set the
  four CLOUD_STRIPE_* env vars (per-key PUT on Render), create the
  webhook endpoint in Stripe pointing at /api/webhooks/stripe, bind all
  ten products via the admin bindings API, verify payments_enabled flips,
  then repeat in live mode. Noted in the phase file.

## Phase 003 — Luna core metering (2026-07-15, luna repo)

Executed in the luna repo (worktree `luna-039-metering`, branch
`039-metering`, plan `plans/039-luna-metering/PLAN.md` there). Three
commits — `716c444` (03910), `6722c5a` (03920), `f93f755` (03930) —
plus a merge of luna main (038 condense work landed mid-phase);
version `0.36.006`.

### What was done

- **03910 — header transport + typed blocks** (`716c444`, 0.36.001):
  `llm_call_scope` context (contextvar) carrying `kind`
  (`agent`/`direct`), `logical_call_id`, `root_action_id`,
  `root_action_type`; a hooked httpx transport injects `x-luna-context`,
  `x-luna-call-id`, `x-luna-root-action-id`, `x-luna-root-action-type`
  on every provider request. `ProviderPolicyBlockedError` (LLMError,
  `retryable=False`, carries `block_code`/`block_retryable`) +
  `policy_block_from_body()` parsing the frozen 402 contract body
  defensively (str/bytes/dict-with-error/dict-with-code/garbage — the
  openai SDK unwraps the `{"error": ...}` envelope before Luna sees it).
  Router `should_fallback` returns False for policy blocks FIRST — a 402
  never tries another provider and never records provider cooldown, under
  every policy (strict/availability/resilient).
- **03920 — call-site classification + lifecycle events** (`6722c5a`,
  0.36.002): `MeteringModel` (pydantic-ai WrapperModel, wraps the
  reasoning model per turn) and inline router emits produce
  `llm.call.started/completed/failed` bus events with the scope ids,
  provider/model, input/output tokens, **cache read/write tokens**
  (anthropic `message_start` usage; openai
  `prompt_tokens_details.cached_tokens`), `cost_usd` on the router path
  and `embed_texts` on embeds. Each request opens a fresh nested scope
  (fresh `logical_call_id`, inherits kind/root action from the outer
  scope; outer kind wins). `utility_complete` and bare `embed()` open
  DIRECT scopes. All emits best-effort — telemetry never blocks a call.
  16 tests.
- **03930 — policy-block propagation to the user** (`f93f755`, 0.36.003):
  one classifier (`_policy_block_notice`) covers both exception surfaces
  (typed error, `ModelHTTPError` 402); `LunaAgent.stream()` yields
  `AgentEvent(kind="policy_blocked", notice={code,message,retryable})`
  then `done` — no fake prose, turn stamped failed, `llm.policy_blocked`
  on the bus. SSE layer forwards a `policy_blocked` event and persists a
  marker row (`extra.kind="policy_blocked"`) so the void is explained on
  reload; both live and persisted paths render one red
  `PolicyBlockedBanner` ("Message not processed"). Non-402 errors keep
  the existing friendly-error path. 8 tests.
- **Dojo** (`dojo/tests/039-policy-block/`, results committed): real
  server on an isolated Postgres DB, anthropic base URL pointed at a mock
  gateway that 402s everything AND records `x-luna-*` headers; the real
  openai key deliberately left configured as the fallback entry. 8/8
  PASS: banner live, banner after reload, no fallback prose row (API
  check), gateway saw `context=agent` + call id + root action id ==
  conversation id + `root_action_type=chat_turn`.
- **Regression**: full luna suite on the merged tree — 1675 passed, every
  failure accounted for as pre-existing: the branch baseline (30) minus
  one 038 fixed, plus two avatar tests reproduced on clean main, plus 13
  live-API tests that only executed because the dojo `.env` supplied a
  dummy anthropic key (they skip without one, as at baseline). Zero
  regressions from 039. UI: tsc clean, vitest 61/61, vite build ok.

### What was learned

1. **pydantic-ai 1.103 made `StreamedResponse.usage` a property** (was a
   method); metering reads it with a `callable()` back-compat check.
   Wrapper-layer code must tolerate both across pydantic-ai upgrades.
2. **The openai SDK unwraps the error envelope**: handlers never see the
   wire body shape, they see `APIStatusError.body` which may be the inner
   error dict. Contract parsers must accept every plausible shape, so
   `policy_block_from_body` is deliberately promiscuous with a safe
   fallback message.
3. **"Retryable" required freezing semantics**: retryable means "retry
   later, same provider" — never "try another provider". Encoding that in
   `should_fallback` (checked before any status-code heuristics) plus a
   no-cooldown assertion is what makes the live no-fallback dojo pass.
4. **The strongest dojo assertion is a real key that must NOT be used**:
   leaving the genuine openai key configured while the primary 402s makes
   wrongful fallback visible as an actual gpt-4o reply. Absence of that
   reply is live proof no code path leaks around the policy block.
5. **A mock gateway doubles as a transport verifier**: having it record
   `x-luna-*` request headers to JSONL turned the UX dojo into an
   end-to-end header-transport test for free (and confirmed
   root_action_id == conversation id on chat turns).
6. **Body-text assertions in browser walkthroughs false-fail**: the word
   "haiku" from the user's own message echoed in the sidebar title;
   asserting via the messages API (no assistant row without the marker
   kind) is exact. Same lesson family as 008's locator notes.
7. **Merging a moved main mid-phase was cheap because surfaces barely
   overlap**: 038 touched runtime/app.py/ChatPanel too, but only
   `__version__` conflicted. `uv sync` after merge (new pillow dep) —
   worktrees don't share the venv.

### Reassessment of future phases

- **009**: gateway↔Luna context reconciliation is now a join on
  `logical_call_id` (Luna emits it in lifecycle events; the gateway
  records it from headers); Luna events are telemetry only — simulator
  inputs stay `billable_events`. Amended.
- **010**: the block-aware image gate is satisfied (luna main 0.36.006);
  the 003 dojo is the canary-stage verification tool (rerun it against
  staging); context-differentiated constants unblocked once canaries run
  the new image. Amended.


## Phase 009 — Simulator and operations (2026-07-15)

### What was done

- **Pricing simulator** (`cloud/billing/simulator.py`, ~1000 lines):
  `create_simulation` pins a manifest (ordered billable-event ids, BOTH full
  config JSONs, provider-cost version) so reruns are reproducible byte-for-
  byte even after late events or edited drafts; transforms are exact
  rationals parsed from decimal strings (global/per-model `cost_multiplier`,
  `volume_multiplier`, full `llm_constants`/tier overrides) — no floats
  anywhere in rating; replay modes `full_demand` and `wallet_constrained`
  (SimWallet replays the real burn order, blocks at zero, tracks debt,
  hit-zero and cash-vs-face basis); funding modes `actual_grants` and
  `candidate_products` (Stripe payments remapped to candidate catalog);
  hosting revenue replayed from config; per-account winners/losers + CSV;
  result carries `result_hash`. Runs execute as a durable `pricing_sim`
  outbox job — cancelled runs never publish (even when cancelled
  mid-compute), retried jobs are idempotent, config errors fail the sim
  while the job succeeds. 25 unit tests including a hand-calculated
  aggregate fixture, exact half-cost integer identities, and a
  never-mutates-production sweep.
- **Operations module** (`cloud/billing/operations.py`, ~590 lines):
  heartbeats table stamped by every background loop; ledger invariants
  (journal trial balance, projection drift vs full replay, grant remainders
  vs consumption history net of reversals); bounded counters — holds by
  status with credits, rated charges by status, shadow `would_block` by code
  (7d — the 010 go/no-go signal), unrated provider:model:dimension gaps,
  outbox by type + dead + `dead_money_jobs` (stripe.*), webhook errors +
  stale queued, hosting stuck-pending / payment_due / active-without-charge,
  scheduled-lot activation backlog, clawback drift vs
  `clawback_target_credits`, unbound Stripe product keys per livemode,
  negative-margin calls. 11 alert rules (severity + dedupe windows,
  thresholds all 0) upserted one row per key: active refreshes in place,
  re-fire inside the window keeps `first_seen_at`, outside resets it.
  `ops_loop` evaluates every 5 min under the billing advisory lock.
  Migration `0006` adds `ops_alerts` + `ops_heartbeats`. 12 unit tests.
- **Admin API** (`billing_admin_routes.py`): `GET /ops`, `GET
  /ops/invariants`, `GET /ops/alerts`, audited `POST /ops/alerts/evaluate`;
  simulations create/list/get/CSV/rerun/cancel with 400 on validation, 409
  on illegal state, audit rows for every mutation. 6 API tests.
- **Admin UI**: `PricingOpsPage` (alerts table + evaluate button, on-demand
  invariant replay cards, counter grid with red alert accents, drill-downs
  that render only when non-empty, heartbeat ages) and
  `PricingSimulationsPage` (create form with version pickers + JSON
  filters/transforms, run list with 3s polling while pending/running,
  detail with baseline/candidate/Δ table + winners/losers, CSV download,
  rerun/cancel). Nav under Pricing; `tsc -b` + vite build green.
- **Restore drill** (`scripts/restore_drill.py`): pg_dump (or an existing
  dump file) → CREATE DATABASE → pg_restore → alembic-head check → invariant
  replay + ops snapshot → report JSON, exit 0 only if everything holds, drill
  DB dropped unless `--keep`. Executed end-to-end against the docker PG:
  PASSED on a seeded ledger; an injected unbalanced posting flipped it to
  FAILED exit 1. (An UPDATE-based corruption attempt was rejected by 001's
  append-only trigger — the trigger provably works.)
- **Dojo** (`tests/039-pricing/dojo_ops_simulator.py`): 11 scenarios on real
  Postgres + real uvicorn with all four background loops live — ops snapshot
  JSONifies (Decimal-cast proof), invariants hold, half-cost simulation runs
  through the REAL 5s worker loop (12 → 9 credits over 3 events), CSV, rerun
  hash-identical, cancel-never-publishes, dead stripe.* job → critical alert,
  all four heartbeats stamped, audit trail, zero `rated_charges` written.
- **Regression**: full suite 579 passed / 1 skipped (43 new tests this
  phase).

### What was learned

1. **Import ledger account constants, never literals**: `operations.py`
   compared `ledger_account == "WALLET"` where the actual value is
   `customer_wallet` — every healthy account looked drifted. The constants
   (`WALLET`, `DEBT`) live in `cloud/billing/ledger.py`; string literals for
   ledger accounts are a bug by construction.
2. **Direct `CreditGrant()` construction needs `burn_priority`** — only
   `create_grant()` fills it from the source-type lookup; a bare model
   instance hits the NOT NULL.
3. **The local dev DB (`lunaservice` on :5435) is a stale pre-Alembic
   snapshot** — missing `agents.color` and `gateway_services.extra_env`, so
   `cloud.db.migrate` correctly refuses to fingerprint-stamp it. Don't use
   it as a drill/dojo source; create fresh DBs on the same server.
4. **pg_dump/pg_restore aren't on the dev host** — only inside the postgres
   container. docker-exec shims work for local drills; the production drill
   runbook must run where real pg tools exist (or download a Render backup
   and use `--dump-file`).
5. **`_sim_out` must exclude manifest event-id lists** from list/detail
   payloads — manifests scale with event count (up to 200k ids) and would
   bloat every list response.
6. **A dojo asserting on the real 5s loops needs no test hooks** — polling
   the public API until the worker finishes is both simpler and stronger
   than exposing run_once to the app.

### Reassessment of future phases

- **010**: restore-drill tooling and a completed local drill satisfy the
  drill *mechanism*; the gate item for enforce mode is rerunning it against
  a production backup. Ops go/no-go signals (would_block by code,
  dead_money_jobs, invariants) are live at `GET /api/admin/pricing/ops`.
  The simulator is the dry-run evidence tool for migration cohorts.
  Amended.
