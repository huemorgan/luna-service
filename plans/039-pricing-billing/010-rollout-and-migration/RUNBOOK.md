# 039/010 rollout runbook

Operational script for the 12-step rollout in PLAN.md. **No step below has
been executed against production — `CLOUD_BILLING_MODE` remains off/unset by
explicit instruction.** Each step lists the concrete action and the evidence
gate that must hold before the next step.

Conventions:
- Env changes on Render: **per-key PUT only** (`PUT /v1/services/{id}/env-vars/{key}`),
  never the bulk list replace. Deploys are manual via the Render API (autoDeploy off).
- Every escalation cites `GET /api/admin/pricing/ops` numbers and requires the
  alert loop quiet (no active critical alerts) and all four heartbeats fresh.
- Reversals: modes and overrides are configuration and reversible; posted
  money/grants/blocks are corrected append-only, never rewritten.

## Step 1 — readiness gates (before any mode change)

- [ ] Full regression green: `.venv/bin/python -m pytest cloud/tests -q` (repo root).
- [ ] Restore drill against a **production backup**:
      download a Render backup, then on a host with matching pg tools
      `python scripts/restore_drill.py --dump-file prod.dump --work-url postgres://localhost:5432/postgres`
      → exit 0 (alembic head match + all three invariants). Local proof: 2026-07-15.
- [ ] Security review checklist (parent plan §Security requirements) signed.
- [ ] Load-test budget recorded (authorization latency target).
- [ ] Daily backups confirmed running on Render.

## Step 2 — global observe

- Render: `PUT CLOUD_BILLING_MODE=observe`, deploy.
- Gate: `/ops` shows rated charges accumulating with status `observed`;
  `would_block` counters populate; zero holds; invariants OK; no ledger rows.

## Step 3 — block-aware Luna image to internal canaries

- Deploy luna `main` @ ≥0.36.006 to canary Lunas (billing stays observe).
- Verify context coverage: compare gateway `billable_events.context` /
  `x-luna-*` headers with Luna lifecycle events; rerun the 003 dojo
  (`dojo/tests/039-policy-block/` in the luna repo) pointed at staging.
- Gate: headers observed on-wire for canary traffic; no fallback-on-402.

## Step 4 — reconcile one complete provider billing period

- Compare provider invoices vs summed `billable_events.vendor_cost_micro_usd`
  per provider for a full calendar period; record variance and threshold.
- Gate: variance within the recorded threshold; discrepancies explained.

## Step 5 — global shadow

- Render: `PUT CLOUD_BILLING_MODE=shadow`, deploy.
- Gate: `/ops` `would_block` by code over ≥7 days matches expectation
  (no mass credits_exhausted on paying-intent accounts); invariants OK;
  `dead_money_jobs = 0`; holds settle within worker cadence (shadow holds
  roll back — the counter must stay 0).

## Step 6 — Stripe live mode (internal canaries only)

- Follow the phase-007 checklist (PLAN.md amendments): live keys via per-key
  PUT, webhook endpoint + signing secret BEFORE announcing, all ten products
  bound for live mode, `CLOUD_BILLING_WORKER=1` on exactly one service.
- Verify with a real small payment: checkout → webhook → grant; refund →
  clawback; failed payment → dunning flag; recovery.
- Gate: `/ops` stripe_bindings.live empty; live smoke ledger entries correct.

## Step 7 — enforce internal canary accounts (override, global stays shadow)

- Admin UI → Pricing → Operations → Enforcement: set override `enforce` on
  the internal accounts (or `POST /api/admin/pricing/enforcement/overrides`
  with the cohort). Reason required; audited.
- Gate: canary Lunas hit real 402s at zero balance with the frozen block
  contract; recovery via top-up works end to end; customers unaffected
  (their effective mode is still shadow).

## Step 8 — open live payments to new accounts (still shadowed)

- Expose Checkout to all accounts; keep global mode shadow.
- Gate: paid grants post correctly for organic signups; reconciliation clean.

## Step 9 — enforce new trial accounts

- Set override `enforce` on accounts created after a chosen date (cohort via
  the same admin API), only after live recovery is proven (step 6/7 evidence).
- Gate: trial-exhaustion → block → top-up → unblock observed on a real
  new account; support volume nominal.

## Step 10 — migrate existing accounts in bounded cohorts

- Owner sign-off (M9) + customer notice (which Luna stays, which stop, date)
  BEFORE execution.
- Dry run per cohort:
  `python scripts/migrate_accounts.py plan --cutover-at <ISO> --account-ids <cohort> --out cohort-N.json`
  Review totals + winners/losers (simulator with `account_ids` filter +
  `wallet_constrained`/`candidate_products` for post-migration block/debt
  preview). The manifest hash pins the evidence.
- Execute: `python scripts/migrate_accounts.py execute --manifest cohort-N.json --actor <name>`
  — aborts with zero writes if live state drifted (exit 2: re-plan, re-review).
- Then set override `enforce` on the migrated cohort.
- Gate per cohort: executed totals match the manifest; invariants OK;
  stop jobs completed (no dead jobs); migrated accounts function under
  enforcement.

## Step 11 — promote enforcement to all accounts

- Render: `PUT CLOUD_BILLING_MODE=enforce`, deploy. Clear now-redundant
  overrides (they are ≤ global and harmless, but tidy).
- Requires: dashboard evidence, recovery evidence, reconciliation evidence
  all linked in the execution report.
- Gate: `/ops` steady state — zero dead money jobs, reconciliation queue
  drained, invariants OK, heartbeats fresh.

## Step 12 — platform-owned paid marketplace items

- Blocked until offer/purchase/entitlement schema, purchase UI,
  refund/revocation policy, and reconciliation exist. Third-party sellers
  stay rejected server-side pending legal/tax/Stripe Connect approval.

## Rollback

- Any step: set `CLOUD_BILLING_MODE` back one stage (per-key PUT + deploy)
  and/or clear account overrides in the admin UI. Money already collected,
  grants posted, and blocks already shown are historical facts — correct
  forward with append-only reversals/gifts, never by rewriting.
