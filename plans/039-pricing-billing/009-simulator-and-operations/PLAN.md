# 039/009 — Margin simulator and operations

**Parent:** `plans/039-pricing-billing/PLAN.md` (Phase G)
**Depends on:** 001 (worker framework), 002, 004 (billable events), 005 (rollups), and
**007 as a hard dependency** — cash basis, invoice/refund state, and candidate product
replay all need it.

## Objective

Admin can rerate real past usage under draft versions and hypothetical scenarios without
touching production records, and operate the system: reconciliation, invariants, alerts.

## Deliverables

### Simulator

- Simulation job/replay engine through the durable worker (job ID + status/result API).
- Inputs: period (default 28 days, capped interactive runs), account/Luna/cohort and
  service/provider/model/context filters, baseline + candidate commercial versions,
  provider-cost basis (original snapshot / latest reconciled / selected version).
- Reproducibility: every run stores an immutable manifest — canonical filter JSON +
  hash, ordered billable-event ID list hash, maximum ledger sequence, baseline/candidate
  config hashes, provider-cost basis version, transforms, replay mode, simulator
  algorithm version, and result hash. Rerun by manifest is identical even after late
  events or reconciled-cost changes ("period + filters" alone is not a snapshot).
- Transforms: global or provider/model/context LLM cost multipliers, explicit overrides,
  volume transforms, target constants — including agent/direct constants by model tier.
  Scenario values are decimal strings/rationals (e.g. `"0.50"`), never floats — the
  no-float invariant applies to simulation too.
- Replay modes: `full demand` and `wallet constrained`. Wallet-constrained replay is
  deterministic — ordering `(effective_timestamp, event_priority, stable_source_id)`;
  grant activation precedes authorization at the same instant; expiration is exclusive
  at `expires_at` — and recomputes candidate estimates and holds from candidate rules
  rather than reusing historical hold amounts.
- Funding modes: `actual_grants` (replays historical grants/cash basis unchanged) and
  `candidate_products` (derives hypothetical grants from historical successful pretax
  payments via the candidate product mapping); results label the mode prominently.
- Outputs: current vs candidate — credits, face value, cash basis from consumed grant
  lots, vendor cost, fixed margin, rounding, gross profit both bases, bonus/gift subsidy,
  accounts reaching zero/debt/limits, blocked demand; deltas, winners/losers, CSV,
  saved reports with config hashes. Face value is never labeled cash revenue.
- Pre-039 `usage_events` appear only as clearly marked estimated coverage.

### Operations dashboards and alerts

- Reconciliation: provider totals vs attributed costs, variances, unknown events, orphan
  Fly Machines/Volumes, failed stops, rerun controls — plus Stripe cash: invoices,
  payments, refunds, and disputes reconcile to local grant/reversal projections.
- Scheduled-lot health: annual activation backlog and missed boundaries detected and
  repairable; debt/dunning ageing visible.
- Worker health: leases, retries, dead letters surfaced with rerun controls.
- Invariants: posted balance vs ledger replay, grant remainders vs projections, journal
  trial balance.
- Alerts (each with threshold, severity, and dedupe window): nonzero trial balance,
  projection drift, paid provider call with no event after timeout, provider variance
  above threshold, negative-margin SKU/context, unbounded/stale exposure, hosting period
  without matching runtime state, webhook/outbox retry exhaustion, scheduled-lot
  activation backlog. Negative balance alerts use age/amount thresholds — bounded debt
  is expected behavior, so a raw negative-balance alert would only make noise.
- Daily backups + one completed restore drill (restore into an isolated DB + invariant
  replay) before enforce mode.

## Tests first

- Rerating never mutates production records; rerun by manifest → identical result, even
  after a late event arrives or reconciled costs change an `original_snapshot` run.
- Rational half-cost transform produces exact integer results with no floats; event
  count/context preserved.
- Changed constant recalculates integer credits with exact ceiling per logical call.
- Same-timestamp events replay in deterministic order.
- `actual_grants` vs `candidate_products` produce labeled differences; candidate hold
  recomputation changes block decisions correctly.
- Full-demand vs wallet-constrained differ in labeled, expected ways.
- Bonus/free grants reduce cash-basis revenue without changing face value.
- Cancelled/retried long jobs never publish partial results; worker crash/lease
  expiry/dead-letter behavior verified.
- Simulation aggregate equals a hand-calculated fixture.

## Exit criteria

- Admin uses real 28-day usage, models an optimized Luna at half vendor cost, adjusts
  constants in a draft, compares margins, saves evidence — and publishing remains a
  separate explicit act.

## Amendments from phase 002 (2026-07-14)

- Ops surfaces have a home: `GET /api/admin/pricing/overview` already reports
  customer liability, uncovered debt, assigned accounts, dead billing jobs,
  and reconciliation holds, and the admin Pricing → Overview page shows a red
  attention banner when dead jobs or holds are non-zero. 009 extends these
  (drill-downs, alerts) rather than adding a new dashboard.
- Candidate versions for the simulator are 002 drafts: immutable-once-published
  configs identified by `config_hash`, cloneable/editable/diffable via the
  admin API. Provider-cost bases map to 002's global effective-dated
  `provider_cost_versions` (rational rates, `quality` estimated/reconciled,
  publish requires a reason and is audited).

## Amendments from phase 004 (2026-07-14)

- The simulator's replay input is now concrete: `billable_events` rows map
  1:1 to `rating.AttemptFacts` (provider, model, dimensions, billable,
  attempt_number, cost_source), and candidate configs replay through
  `rating.rate_call` — same single-margin single-ceil path production uses.
  No parallel rating implementation.
- New ops counters to surface on the overview/drill-downs:
  `needs_reconciliation` rated charges (usage_missing cases), stale-hold
  reaper conversions, `would_block` frequency by code from shadow mode
  (shadow is the pre-enforce dress rehearsal — its would_block rates are the
  go/no-go signal for 010's enforce flip), and unrated-dimension occurrences
  (rate-table gaps recorded by rating).
- Provider-rate gaps are visible data: rating records unrated dimensions in
  the rule snapshot instead of guessing — the ops page should list distinct
  `provider:model:dimension` gaps so the cost table can be completed.

## Amendments from phase 005 (2026-07-14)

- New ops counters: periods stuck `pending` (provisioning limbo) or
  `payment_due` (dunning backlog); dead `hostprov` / `hostsusp` /
  `teardown` outbox jobs; periods activated WITHOUT a charge
  (`charge_transaction_id IS NULL` — the settle-failed/hold-missing path
  logs and activates; ops must reconcile these by hand).
- Simulator: hosting revenue is pure config replay (price_credits ×
  periods per account) — include it so config candidates show total bill
  impact, not just LLM usage deltas.
- Reaper/renewal visibility: the maintenance loop expires grants and
  renews periods on a 60 s cadence — ops page should show last-run
  timestamps for maintenance ticks like it does for the outbox worker.

## Amendments from phase 008 (2026-07-14)

- The customer usage API (`/api/billing/usage/summary`) already ships a
  depletion projection: plain average of the selected range's daily trend,
  `projection_is_estimate: true`, UI labels it "estimate". The simulator
  must not invent a second customer-facing projection — reuse these
  semantics (or refine them in place) so the admin simulation and the
  customer number never disagree.
- Customer-facing attribution groups by root action and counts multi-attempt
  calls once (first-event-per-call). Simulator/ops views that reconcile
  against customer numbers must use the same rule, or totals will differ
  from what the customer sees on their own page.
- Postgres returns `Decimal` for SUM aggregates where SQLite returns int —
  cast before arithmetic; a Decimal/float mix 500ed in phase 008 and only
  the PG dojo caught it.

## Amendments from phase 007 (2026-07-14)

- New operational surfaces that ops pages/alerts must cover:
  - **Billing-job dead letters**: jobs stuck `pending` with rising
    `attempts` or `dead` (max 8 attempts) — a dead `stripe.*` job means
    money moved in Stripe with no local grant/clawback. Highest-severity
    signal on the ops page.
  - **processed_webhooks in state `error`** and events `queued` older
    than a few minutes (worker stalled or handler crash-looping).
  - **Clawback drift**: `stripe_payments.refunded_pretax_cents /
    disputed_pretax_cents / clawed_credits` should reconcile against
    Stripe's own refund/dispute totals; the simulator should compute
    `clawback_target_credits` from Stripe data and diff.
  - Unconfigured-gateway retries (`StripeConfigMissing` in
    `last_error`): payments env got wiped while webhooks kept arriving.
- Webhook simulation: replay canned Stripe event fixtures through
  `intake_event` + the real worker (fake gateway via the module-level
  `gateway_factory` seam), never by calling handlers directly — the
  dedupe + durable-job path is where production bugs live.
- The `payments_enabled` derivation (settings + full binding coverage) is
  itself worth an ops check: show WHICH product keys are unbound per mode.
