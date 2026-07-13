# 039/005 — Grants, hosting periods, limits, services, and resources

**Parent:** `plans/039-pricing-billing/PLAN.md` (Phase D)
**Depends on:** 001 (ledger, durable worker framework), 002 (the assigned commercial
version supplies trial amount, active-Luna cap, and hosting price), 004 (billing service
in the runtime path; non-LLM adapters plug into 004's deny-by-default route framework)

## Objective

Wire every non-gateway cost surface into the ledger: trial gifts, expiry, per-Luna
limits, the 999-credit hosting lifecycle, service/job/storage accrual, and marketplace
purchases. After this phase every launch cost surface is metered, included, or disabled.

## Amendments from phase 001 (2026-07-13)

- Already implemented in 001's ledger — this phase wires products/workers onto them, not
  new mechanics: debt repayment on grant (no double wallet movement), scheduled lots
  (post only at activation; `activate_scheduled_grants` exists), expiration with
  exclusive boundary, per-Luna daily/monthly limit periods with settle-time settlement
  and release draining, `count_toward_limits=False` for hosting charges.
- Grant `source_type` is check-constrained to `subscription_paid`, `subscription_bonus`,
  `topup`, `free_recurring`, `gift`, `refund`, `admin` — it is not the visible category
  (bonus/gift/free/paid/topup). Trial and migration gifts use `gift`; map explicitly.
- Renewal-anchor and expiry math done in Python against DB-loaded datetimes must
  normalize naive→aware (`_aware()` in ledger.py) — SQLite tests return naive values.
- Provisioning and renewal jobs run as `billing_outbox` handlers on the 001 worker
  (leases, backoff, dead-letter). Handler contract: `run_claimed_job` rolls back on
  handler exception, so a handler must be re-runnable from its committed job row alone.

- New-account creation atomically creates the billing account, commercial assignment,
  and one trial gift (1,800 credits, 28 days) in the same transaction — exactly once
  under concurrent signup callbacks. Amounts come from the assigned version. No
  recurring free grant exists.
- Trial accounts have an active-Luna maximum from the assigned version (default 1);
  concurrent creates cannot exceed it.
- Expiry worker: locks and consumes only remaining grant credits, append-only expiration
  transactions, idempotent reruns.
- Scheduled-lot activation worker (yearly buckets): activates every scheduled lot with
  `effective_at <= now` under a row lock, exactly once, on the 001 worker framework;
  recovers correctly when delayed past several boundaries. Tests inject the clock.
- Hold reaper: a stale hold is released only when no external work started. Once
  dispatch/provisioning may have begun, expiry transitions it to
  `needs_reconciliation` — never a silent release after possible spend.
- Admin gift flow with reason + confirmation preview (default 90-day expiry, editable).

### Per-Luna limits

- Nullable daily/monthly credit limits, warning thresholds, audited changes.
- UTC calendar periods with exact reset timestamp exposed.
- Limits measure consumption only — hosting charges never count toward them.
- Lowering below current usage blocks new actions immediately without rewriting history.
- One Luna at its cap never blocks another Luna while the account is positive.

### Hosting lifecycle (999 credits, basic tier)

- Creation is transactional and durable: lock the billing account, enforce the
  active-Luna cap, create a pending agent + hosting period, authorize exactly 999,
  enqueue durable provisioning work (001 worker framework — today's
  `asyncio.create_task(provision_luna_for_account(...))` in `agent_routes.py` loses paid
  work on process death). Provisioning runs outside the transaction; confirmed runtime
  resources settle the hold and activate the period; every partial state is idempotently
  recoverable. Fly network calls never run inside an open DB session.
- The 999 basic hosting SKU **includes** the basic Fly machine and bundled base volume:
  those resources are tracked as operator cost but never separately customer-charged —
  no double-charging via resource accrual. Only explicitly defined excess storage or
  separate job resources get additional SKUs.
- During a paid period: allocation persists even if the account goes negative; blocked
  accounts serve stored UI/history only — no LLM, paid service, job, new resource, or
  start/restart. Manual stop/start inside an active paid period is free.
- Every start, retry, provision, auto-wake, scheduler, and relay path passes through one
  hosting-state guard. A `payment_due` Luna cannot be auto-woken by proxy traffic or any
  other path; restart requires debt cleared + a newly paid hosting period.
- Renewal at the Luna's monthly anchor, clamped for short months: a Jan 31 anchor renews
  on the last day of February and returns to Mar 31. Notify before renewal if balance
  cannot cover; exact 999 authorization at period end; failure stops the runtime, marks
  `payment_due`, keeps data per retention policy.
- Agents are soft-deleted tombstones: runtime/volume cleanup is durable outbox work;
  financial and usage attribution is never deleted (agent hard-delete today conflicts
  with permanent attribution).
- Runtime allocation hooks at the `LunaRuntime` interface; provider reconciliation
  confirms stopped resources actually stopped (failed stop = operator-visible leak).

### Services, jobs, storage, marketplace

- Gateway services: hold before proxy, rate from provider response or versioned
  fixed-per-action SKU.
- Job envelopes (browser/code; forge lands with 034): authorize before launch, attach
  child events, stop new child work at the cap, settle actual usage. Forge jobs will
  additionally accrue the forge machine-time SKU.
- Scheduler/WhatsApp/relays: signed idempotent callbacks; precheck where Luna funds the
  action.
- Storage: periodic byte/operation snapshots, idempotent interval accrual.
- Fly Machines/Volumes: lifecycle allocation records + periodic accrual.
- Marketplace: exact-price authorization, atomic purchase + entitlement (platform-owned
  items only).
- Usage rollups (rebuildable, never financial source of truth).

Note: all non-LLM SKUs are seeded disabled in version 1. This phase builds the metering;
each SKU is enabled by publishing a version with its price defined. Jobs, paid storage,
and marketplace charging stay disabled until each has a durable authority, idempotent
source event, concrete price, and enforcement point (marketplace items are currently
usable without any entitlement check — that check lands with the entitlement schema).

## Tests first

- Gift/expiry/renewal jobs safe to rerun; duplicate/out-of-order resource events cannot
  double-accrue.
- Concurrent account callbacks issue one trial gift; concurrent Luna creates on a trial
  account provision one Luna and charge hosting once.
- Crash/retry at every provisioning state recovers idempotently.
- Manual stop/start during an active period creates no second hosting charge.
- Payment-due Luna cannot auto-wake through proxy, scheduler, relay, or retry routes.
- Jan 31 anchor renews on the last day of February and returns to Mar 31.
- Early deletion preserves agent identity, hosting charge, and statement.
- Base machine/volume are not separately customer-charged.
- Stale hold with possible spend becomes `needs_reconciliation`, never released.
- Hosting charges exactly once per confirmed period; failed provisioning releases or
  reconciles; debt during a paid period blocks paid work without double-charging hosting.
- Failed renewal stops the Luna; restart impossible without debt cleared + 999.
- Marketplace item cannot be used without entitlement (once entitlements exist);
  non-owner cannot change limits, gifts, hosting, or payment state.
- Hosting charge does not consume per-Luna limit budget.
- One Luna's limit blocks it alone; account block stops all Lunas.
- Trial expiry blocks paid work; Luna stops at the end of its already-paid month.

## Exit criteria

- Account and per-Luna statements cover every enabled surface: hosting, LLM, and enabled
  services. Disabled surfaces (jobs, paid storage, marketplace) are reported as
  disabled — never claimed as statement coverage.
- Every launch cost surface is explicitly metered, included, or disabled.

## Amendments from phase 002 (2026-07-14)

- The signup hook already exists: `_upsert_user_and_account` creates the
  billing account and the commercial assignment (`source=new_account_default`)
  in the same transaction, and tolerates unseeded billing (account created,
  zero assignments, warning logged). 005 adds the trial gift into this path;
  it must handle the no-assignment edge the same way — amounts come from the
  assigned version, so no assignment means no gift plus a reconcile signal,
  never a crash of signup.
- Trial parameters live in the assigned version's `config.trial`
  (`gift_credits` 1,800, expiry days, per-Luna day/month caps,
  `max_active_lunas` 1) and `config.migration_gift`. Read them from the
  account's assignment — never from constants; the admin can change them by
  publishing a new version.
- Hosting invariant enforced by 002 validation: `config.hosting.price_credits`
  must equal the `hosting_month` SKU's `price_credits` constant. Hosting
  charge code should read the SKU constant so there is one source of truth.
- Renewal/provisioning handlers: follow 002's rollout handler pattern —
  `register_handler(...)` at module import, `dedupe_key` naming like
  `pricing_rollout:{id}`, and restart idempotency proven by re-running the
  handler against committed audit/state (`audit_ref`) rather than in-memory
  progress.
