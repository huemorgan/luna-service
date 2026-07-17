# 047 — Payment → grant tracking (dojo scenarios)

Make "money came in, we granted nothing" loud, durable, and inspectable
from the admin API/UI. Runner: `dojo_payment_grant.py` (headless Playwright
+ real Postgres, admin session).

Seed: one money-in outbox job that **succeeded but granted nothing**
(`stripe.invoice_paid`, `result.granted = false`, reason recorded), one
**healthy** money-in job (`result.granted = true` — must NOT be flagged),
and one unrelated **dead** job.

## S1 — Overview surfaces the anomaly

- Go to `/admin/pricing`.
- PASS: a "Payments granted nothing" stat reads **1** and is styled as an
  alert; the red "needs operator attention" banner is visible.

## S2 — Ops page detail

- Go to `/admin/pricing/ops`.
- PASS: "Payments granted nothing" stat = **1**; a "Payments that granted
  nothing" section lists the job with its `job_type`, id/event, and the
  skip **reason**.

## S3 — Admin API detail + filtering

- `GET /api/admin/pricing/billing-jobs` (default = attention set).
- PASS: returns the granted-nothing job with full detail (`payload`,
  `result`, `last_error`) AND the dead job; the **healthy** grant is
  excluded. `?status_filter=succeeded` returns succeeded jobs incl. the
  healthy one. `overview.payments_granted_nothing == 1`.
