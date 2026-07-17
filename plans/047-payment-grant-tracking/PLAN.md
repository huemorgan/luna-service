# 047 — Payment → grant tracking

## Why

A live `recurring_99` subscription went **active** but granted **0 credits**
(account `vaselin`). The `invoice.paid` outbox job had dead-lettered, and the
only observable signal was `dead_billing_jobs: 1` on the admin overview — a bare
count with no job type, payload, or `last_error`. Worse, the *silent* variant —
a money-in webhook that runs to `succeeded` but hits a `_skip` gate and grants
nothing (`result.granted == false`) — leaves **no trace at all**: no error, no
alert, indistinguishable from a healthy grant.

We couldn't tell *why* the grant failed without direct prod DB access. That's the
gap this plan closes: make "money came in, we granted nothing" **loud, durable,
and inspectable from the admin API**.

## Scope (no schema migration — reuses existing columns)

1. **Loud + durable at the source** (`billing/stripe_webhooks.py`)
   - `MONEY_IN_JOB_TYPES = {stripe.invoice_paid, stripe.checkout_completed}`.
   - When such a job finishes without a grant, the handler wrapper logs at
     `ERROR` and stamps the `processed_webhooks` row: `state="granted_nothing"`,
     `last_error=<skip reason>`. A normal grant still stamps `processed`.

2. **New anomaly counter** (`billing/operations.py`)
   - `payments_granted_nothing`: money-in outbox jobs in `succeeded` that
     produced no grant (the silent case dead-job counters miss), with detail
     (`event_id`, `object_id`, `reason`, `at`).
   - New critical `AlertRule` + threshold 0, wired into `_signals`.
   - `_webhook_counters` also counts the new `granted_nothing` state.

3. **Inspectable from admin API** (`api/billing_admin_routes.py`)
   - `GET /api/admin/pricing/billing-jobs?status=&limit=` → full job detail
     (`job_type`, `status`, `attempts`, `payload`, `result`, `last_error`,
     timestamps). Default = attention set (dead + payments-granted-nothing).
   - `overview` gains `payments_granted_nothing`.

4. **UI surfacing**
   - Overview: "Payments granted nothing" stat, folded into the attention banner.
   - Ops page: stat + drill-down listing each anomaly's reason.

## Out of scope

- Retrying/replaying dead jobs from the UI (separate, needs a mutating audited
  endpoint). This plan is read/observability + source-side recording only.

## Tests

- webhook handler: a money-in event that skips marks `granted_nothing` + reason.
- operations: `payments_granted_nothing` picks up a succeeded-no-grant job.
- admin: `/billing-jobs` returns detail and filters by status.
