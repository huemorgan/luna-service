# 039/010 — Rollout, enforcement, and account migration

**Parent:** `plans/039-pricing-billing/PLAN.md` (Rollout + Required verification)
**Depends on:** all prior phases; 003's compatible Luna image gates context pricing

## Objective

Turn the system on for real customers, in reversible steps, without deleting or
rewriting financial history at any point.

## Amendments from phase 001 (2026-07-13)

- Production schema adoption is already built and deploy-integrated: the Dockerfile CMD
  runs `python -m cloud.db.migrate` before uvicorn. On the first deploy of this branch,
  prod (pre-Alembic) is fingerprinted (table/column existence only), stamped `0001`, and
  upgraded to `0002` automatically; a fingerprint mismatch aborts the deploy with no
  writes and Render keeps the old instance serving. Known tolerated drift:
  `users.is_admin` nullable in prod vs NOT NULL in the baseline.
- Anything invoking Alembic against a non-default DB (ops scripts, restore drills) must
  set `CLOUD_DATABASE_URL` — `alembic/env.py` prefers it over the ini/programmatic URL.
- Migration gift grants use source key `migration:{account_id}:v1` with source_type
  `gift`; idempotent reruns return the prior transaction via the ledger's
  operation-ID + canonical-hash scheme.

`CLOUD_BILLING_MODE` is global, and `selected_accounts` is a pricing-assignment
audience — neither can enforce only internal accounts. Add a nullable per-account/cohort
enforcement override with audited effective timestamps. The gateway resolves
`off < observe < shadow < enforce` as the maximum of the global mode and the account
override, so internal canaries can be enforced without touching customers.

## Rollout sequence

Ordering rules baked in: live payment recovery exists **before** any customer-facing
enforcement (a blocked trial customer must have a real top-up path), and the
block-aware Luna image ships **before** any account is enforced (old images retry or
render raw errors).

1. Unit/property/concurrency suites green with synthetic credits; security review
   (gateway identity, context resolution, payments, admin mutations — parent plan
   §Security requirements), backup/restore drill, and load-test budget (review M4)
   complete.
2. Production `CLOUD_BILLING_MODE=observe`: meter and rate only; no debits, no blocks.
3. Deploy the compatible Luna image (003) to internal canaries while billing stays
   observe; verify context coverage by comparing gateway contexts with Luna lifecycle
   events. The image is required before context-differentiated constants.
4. Reconcile at least one complete provider billing period with explicit variance
   thresholds.
5. `shadow`: full ledger/hold decisions in an isolated shadow ledger; compare balances
   and block decisions against expected behavior.
6. Configure Stripe live mode (livemode-checked keys via per-key Render PUT; live tax
   registrations recorded), exposing Checkout only to internal canaries; verify a real
   small payment, grant, refund, failed payment, and recovery.
7. Enforce internal canary accounts via the per-account enforcement override.
8. Open live subscriptions and top-ups to new accounts while they remain shadowed.
9. Enforce new trial accounts with version 1 — only after live recovery is proven.
10. Migrate existing accounts in bounded cohorts (dry run first; see below).
11. Promote enforcement to all accounts only with dashboard, recovery, and
    reconciliation evidence.
12. Enable platform-owned paid marketplace items — only after marketplace
    offer/purchase/entitlement schema, customer purchase UI, refund/revocation policy,
    and reconciliation exist. Third-party sellers stay hard-disabled (rejected
    server-side) pending legal/tax/Stripe Connect approval.

Reversibility, stated honestly: operational modes and future assignments are
reversible; collected money, posted grants, expirations, and customer-visible blocks
are not undone by configuration. Financial history is never deleted or rewritten —
mistakes are corrected through append-only reversals or replacement assignments.

## Existing-account migration

Proposed decision for review M9 (owner sign-off required before execution):

- Define `cutover_at`. Accounts created at or after it get the default new-account
  assignment and normal trial grant. Every pre-cutover account is migrated idempotently
  with source key `migration:{account_id}:v1`.
- Migrated accounts get exactly the trial treatment (owner decision): one 28-day
  `migration` gift of 1,800 credits (999 hosting + 801 activity at version-1 defaults;
  configurable as a versioned product like the trial gift) and a one-active-Luna limit.
  Reconcile actual runtime state first, then keep the account's most recently active
  Luna running: charge it 999 and open its first hosting period at migration time. Every
  other running Luna is stopped at migration — not deleted, data retained per the
  retention policy — and restarting one later requires the normal debt-cleared + 999
  payment (and, while on the trial-equivalent limit, stopping or upgrading past the
  active one). Stopped/error Lunas likewise get no hosting period.
- Customer notice ahead of migration: which Luna stays up, which will be stopped, and
  the date — sent before `cutover_at`, not discovered after the fact.
- The dry run records account count, running/stopped/error Luna counts, which Luna
  stays running per account, Lunas to be stopped, total grants, total immediate hosting
  charges, resulting liability, assignment counts, and a content hash; execution must
  match those totals or stop. Reruns return prior results;
  corrections are append-only. Migration handles accounts created while it runs
  (cutover boundary, not a race).
- Legacy `Account.plan` stops being billing authority; subscription/product state comes
  from billing projections, and UI stops presenting `Account.plan` as the paid plan.

## Data retention

Plan 039 performs no automatic customer-data deletion for nonpayment. A failed hosting
renewal stops compute but retains the tenant database, R2 data, and Volume until a
separately approved retention/deletion policy exists.

## Required verification before enforce/live

- Ledger property tests + real Postgres concurrency tests.
- Migration test against a production-shaped backup **and** a signed dry-run manifest
  with expected totals before any real mutation.
- Provider contract fixtures for every enabled model/service.
- Failure injection at each external-call/DB-commit boundary.
- Stripe CLI + test-clock webhook suites; live-mode livemode-mismatch rejection.
- Reconciliation against real provider usage (the complete-period reconciliation moved
  here from 004's exit criteria).
- Browser dojo: trial grant → subscribe → spend → limits → debt → top-up → recovery.
- Live agent walkthrough: chat, tool loop, playbook, background/summarization, blocked
  behavior on the compatible image.
- Load tests: authorization latency (budget set in step 1), statement queries, rollups,
  simulator jobs.
- Daily backups running and one restore drill completed.

## Exit criteria

- All accounts on explicit immutable assignments; every parent-plan Definition of Done
  item checked and evidenced in the execution report.
