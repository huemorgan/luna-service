# 039/007 — Stripe integration: subscriptions and top-ups

**Parent:** `plans/039-pricing-billing/PLAN.md` (Phase E)
**Depends on:** 001 (grants/ledger, durable worker framework), 002 (published version-1
catalog and rollout renewal-migration intents), 005 (scheduled-lot activation worker),
006 (Stripe account, bindings). All webhook, retry, dead-letter, scheduled-grant, and
auto-top-up work runs on the 001 durable worker — never in-process lifespan tasks.

## Objective

Real money in: Stripe Checkout for buckets and top-ups, verified durable webhook
processing, paid + bonus + yearly-gift grant issuance, upgrade/downgrade/cancel,
refunds/disputes. Test mode first; live mode is flipped during rollout (010).

## Deliverables

### Stripe objects and flows

- One Stripe Customer per Luna `Account` (concurrent creation produces exactly one);
  SDK/config wiring (`CLOUD_STRIPE_*` settings) and `.env.example` docs.
- Plan changes are code-owned. Checkout creates the **first** subscription only; at most
  one active Luna Credits subscription exists per account. An upgrade updates the
  existing subscription with `payment_behavior=pending_if_incomplete`,
  `proration_behavior=none`, `billing_cycle_anchor=now`; the new full bucket is granted
  only from the resulting verified paid invoice — a failed upgrade payment leaves the
  old subscription unchanged. A downgrade is stored as a period-end pending change and
  applied idempotently at renewal. Billing Portal handles payment method, invoices, and
  period-end cancellation only (plan switching disabled in 006).
- Top-ups from fixed server-returned steps only — the browser can never submit an
  arbitrary amount; metadata carries account, versioned step key, expected credits, and
  an unguessable server operation ID.
- Subscription metadata: account, product key, commercial pricing version.
- Optional auto-top-up: off by default; requires explicit threshold, step, saved payment
  method, and a monthly cash cap. An off-session payment that requires customer action
  (SCA) enters a stable failed state with a customer CTA — never a retry loop of new
  PaymentIntents.

### Webhook processing (durable, idempotent)

- Verify signatures against the raw body; reject `livemode` mismatches; persist/dedupe
  events in `processed_webhooks` before any work; retrieve canonical objects on
  out-of-order delivery.
- `invoice.paid` alone is not proof of collected money (Stripe emits it for zero-value,
  credit-funded, or manually-marked-paid invoices). The handler retrieves the canonical
  Invoice/Subscription and validates account, Price binding, currency, nonzero pretax
  line amount, payment source, and active subscription state before granting.
- Subscription grants: monthly buckets issue one `subscription_paid` + one
  `subscription_bonus` lot; yearly buckets issue twelve scheduled monthly paid lots,
  monthly bonus lots where configured, and the single yearly gift lot. Every lot uses a
  compound idempotency key `stripe:{invoice_id}:{product_key}:{paid|bonus|gift}:{lot_index}`
  (an invoice ID alone cannot identify up to 25 lots); a duplicate webhook returns the
  previously created lots.
- Annual lot boundaries: `period_start + i` calendar months using the original anchor
  day clamped to each month's last day; lot 12 ends exactly at Stripe's annual
  `period_end`. Activation is the 005 scheduled-lot worker (injected clock). Note:
  Stripe Test Clocks advance Stripe's clock only — tests advance the test clock, then
  run the activator at the clock's frozen time.
- Verified successful PaymentIntent/Checkout payment → top-up grant. Never grant from
  `success_url`, browser state, or non-final `checkout.session.completed`.
- Refunds/disputes against immutable lots: reversal is cumulative and proportional to
  the refunded **pretax** product amount — per lot, target reversed credits =
  `floor(original_credits × cumulative_refunded_product_amount / original_product_amount)`,
  capped at the lot; a full refund reverses any rounding remainder. Scheduled credits
  cancel first, then active/unconsumed, then consumed (may create debt). Tax and fees
  map to zero credits. Disputes share the same payment-level clawback accumulator:
  `created` applies the disputed target once, `won` restores via new postings, `lost`
  makes no second reversal — refund + dispute never double-claw.
- Dunning (decides review M6): no credit grace period at launch. A failed renewal
  creates no grants and marks billing `past_due`; existing lots expire normally; top-ups
  may restore a positive spendable balance while past due; a later verified payment
  grants once and clears the notice.
- A marketplace entitlement (when marketplace ships) survives a funding-payment refund
  but is unusable while account debt blocks hosted activity; refunding the marketplace
  purchase itself atomically revokes the entitlement.
- All handlers idempotent through the durable worker with retry/dead-letter visibility.

### Plan changes

- Upgrade (mechanics above): the full new bucket is granted once from the verified paid
  invoice; the anchor resets on successful payment; still-valid old grants keep their
  original expiry.
- Downgrade/cancel: applied at next renewal.
- Yearly refund: cancel not-yet-effective scheduled lots first, reverse the rest under
  the proportional reversal rules.
- No credit for Stripe proration until the corresponding invoice is paid; promotion
  codes/discounts are unsupported unless explicitly added to the paid-credit invariants.

## Tests first

- Duplicate/out-of-order webhooks grant exactly once (Stripe CLI replay); one annual
  invoice creates exactly 12 paid lots, configured bonus lots, and one gift with
  distinct keys.
- Zero-value, out-of-band, wrong-currency, and wrong-Price invoices grant nothing.
- Browser return grants nothing; only verified webhooks do.
- Failed → pending → later-successful payment sequences behave correctly; immediate
  failed-renewal block, Smart Retry/later payment, top-up while past due.
- Top-up step cannot be altered client-side.
- Refund of already-spent credits posts the reversal and may create debt; full/partial
  refund, refund failure, dispute won/lost, and refund-plus-dispute never double-claw.
- Upgrade grants once and resets the anchor; upgrade payment failure leaves the old
  subscription unchanged; downgrade waits for renewal.
- Jan 29/30/31 and leap-year lot boundaries; worker delayed past several boundaries
  activates every due lot once.
- Auto-top-up races create one payment; SCA failure lands in the stable failed state;
  monthly cash cap and its rollover respected.
- Webhook crash before/after event insert, outbox insert, Stripe retrieval, and ledger
  commit recovers exactly once.
- Stripe test clocks + injected application clock: monthly renewal, yearly renewal with
  scheduled lot activation, failure and recovery cycles.

## Exit criteria

- Real Stripe test-mode money-in maps exactly once to visible grant lots and receipts,
  including the yearly twelve-lot + gift issuance.
