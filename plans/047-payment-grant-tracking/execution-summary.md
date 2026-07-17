# 047 — execution summary

_2026-07-17_

## What was accomplished

Shipped "money came in, we granted nothing" observability end-to-end. No schema
migration (reuses existing columns / states).

- **Source recording** (`cloud/billing/stripe_webhooks.py`): added
  `MONEY_IN_JOB_TYPES = {stripe.invoice_paid, stripe.checkout_completed}`. The
  `_handler` wrapper now inspects the result: a money-in job that finishes
  without `result.granted` logs at `ERROR` and stamps the `processed_webhooks`
  row `state="granted_nothing"` with the skip reason (via a `state`/`note`
  extension to `_mark_processed`). Normal grants still stamp `processed`.
- **Anomaly counter** (`cloud/billing/operations.py`): `_payments_granted_nothing()`
  scans succeeded money-in outbox jobs whose `result.granted` is falsey and
  returns `count` + `detail` (`event_id`, `object_id`, `reason`, `at`). Wired
  into `ops_snapshot`, a new critical `AlertRule` (threshold 0), and `_signals`.
  `_webhook_counters` also counts the new `granted_nothing` webhook state.
- **Admin API** (`cloud/api/billing_admin_routes.py`): new
  `GET /api/admin/pricing/billing-jobs?status_filter=&limit=` returns full job
  detail (`payload`, `result`, `last_error`, timestamps). Default response is the
  attention set — dead jobs + succeeded money-in jobs that granted nothing;
  healthy grants are excluded. `overview` gains `payments_granted_nothing`.
- **UI**: Overview (`PricingOverviewPage.tsx`) shows a "Payments granted nothing"
  alert stat folded into the attention banner; Ops page (`PricingOpsPage.tsx`)
  shows the stat plus a "Payments that granted nothing" drill-down listing each
  anomaly's job type, id/event, and reason.

## Tests

- Backend unit: `test_billing_stripe_webhooks.py`, `test_billing_operations.py`,
  `test_billing_admin_api.py` — **65 passed**.
- Dojo E2E (`tests/047-payment-grant-tracking/dojo_payment_grant.py`, headless
  Playwright on real Postgres, admin session): S1 overview alert + attention
  banner, S2 ops detail with skip reason, S3 `/billing-jobs` detail + attention
  set excludes the healthy grant + `status_filter=succeeded` includes it +
  `overview.payments_granted_nothing == 1`. **All pass.** Screenshots under
  `tests/047-payment-grant-tracking/results/`.

## Discovered along the way

- The original prod incident (`vaselin`, `recurring_99`) had only
  `dead_billing_jobs: 1` as a signal — no type/payload. The *silent* case
  (succeeded + `_skip` → no grant) had **no** signal at all; that's why the
  counter keys off `result.granted` rather than job status.
- The "granted" flag lives in a JSONB `result` column. The attention-set filter
  in `/billing-jobs` does the SQL-level status/type narrowing but applies the
  `result.granted` predicate in Python so it stays portable across the SQLite
  test DB and Postgres.

## Things to consider in the future

- Retrying/replaying dead or granted-nothing jobs from the UI is deliberately
  out of scope (needs a mutating, audited endpoint). This plan is
  observability + source-side recording only.
- Alert fires via the background worker's periodic evaluate; threshold is 0 so
  any single anomaly pages. Watch for false positives from legitimate
  zero-credit money-in events (none today) before relaxing.
