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
