# 039/006 — Stripe account and product setup (browser session)

**Parent:** `plans/039-pricing-billing/PLAN.md` (Phase E prerequisite)
**Depends on:** 002 (validated — not yet published — version-1 draft catalog). Ordering:
006 consumes the validated draft, enters environment bindings, and only then does 002
publish version 1; publication itself never requires Stripe (see 002). This avoids the
002↔006 circular dependency.
**Mode:** interactive — Roy creates the Stripe account; Claude drives the browser to
configure products, tax, portal, and webhooks. No luna-service code in this phase.

## Objective

A fully configured Stripe account (test mode first) whose products map one-to-one to the
versioned product keys in commercial version 1, with webhook endpoints and restricted
keys ready for 007.

## Checklist

### Account (Roy, manual)

1. Create the Stripe account; complete the business profile, payout bank details, and
   identity verification (live mode can verify later — test mode does not block).
2. Enable two-factor auth.

### Products and prices (Claude in browser, test mode)

Create one Product per versioned product key, with lookup keys matching the version
config:

| Product key | Price | Interval |
|---|---:|---|
| `hobby_19_monthly` | $19.00 | monthly |
| `hobby_19_yearly` | $228.00 | yearly |
| `recurring_100_monthly` | $100.00 | monthly |
| `recurring_100_yearly` | $1,200.00 | yearly |
| `recurring_200_monthly` | $200.00 | monthly |
| `recurring_200_yearly` | $2,400.00 | yearly |
| `topup_10` | $10.00 | one-time |
| `topup_25` | $25.00 | one-time |
| `topup_50` | $50.00 | one-time |
| `topup_100` | $100.00 | one-time |

Credits are granted by Luna's ledger from webhook events — Stripe products carry money
and metadata only, never credit amounts as a source of truth.

### Tax, portal, and settings

- Enable Stripe Tax and set the origin address, knowing this alone collects nothing:
  collection requires registrations plus `automatic_tax=true` on every
  Checkout/subscription flow (007). Before live mode, record the approved tax treatment
  and Product Tax Code **separately** for recurring buckets, top-ups, and future
  marketplace purchases — they may differ. Tax and Stripe fees never grant credits;
  credits derive from the pretax product amount only.
- Billing Portal is limited to payment methods, invoice history, tax IDs, and period-end
  cancellation. **Portal plan switching is disabled entirely** — Stripe plan changes are
  code-owned (007): Checkout starts a new subscription only; Luna's billing API performs
  upgrades and schedules downgrades. (Portal scheduled downgrades only work between
  Prices of the same Product and cannot implement the "full new bucket, reset anchor,
  grant once" policy.)
- Set statement descriptor, support email, and branding (name/logo/colors).
- Payment methods: card (+ Link); defer others until requested. No delayed-notification
  payment methods at launch.

### Webhooks and keys

- The webhook endpoint is created **only after the 007 route is deployed** to the test
  environment — configuring it first just accumulates retries against a nonexistent
  route. Endpoint: `https://<service>/api/billing/webhooks/stripe`. Events:
  `invoice.paid`, `invoice.payment_failed`, `invoice.finalized`,
  `payment_intent.succeeded`, `payment_intent.payment_failed`,
  `checkout.session.completed`, `customer.subscription.updated`,
  `customer.subscription.deleted`, `refund.created`, `refund.updated`, `refund.failed`,
  `charge.dispute.created`, `charge.dispute.closed`. The handler rejects any event whose
  `livemode` does not match the environment.
- Record the webhook signing secret.
- Create a restricted API key mapped to the actual SDK calls 007 makes — write:
  Customers, Checkout Sessions, Subscriptions, Billing Portal, PaymentIntents,
  SetupIntents, PaymentMethods (auto-top-up), Refunds; read: Invoices, Charges,
  Products/Prices, Disputes. Verify the key executes every expected call and rejects
  unrelated APIs. Do not use the unrestricted secret key in the service.
- Store `CLOUD_STRIPE_SECRET_KEY` (restricted), `CLOUD_STRIPE_WEBHOOK_SECRET`,
  `CLOUD_STRIPE_PUBLISHABLE_KEY`, and explicit `CLOUD_STRIPE_LIVEMODE=false|true` in
  Render via per-key PUT (never bulk env replace) and in `.env.example` documentation.
  The `CLOUD_` prefix is required — settings load through the Pydantic `Settings`
  prefix; bare `STRIPE_*` names would not load.
- Record each product/price ID as an environment binding to its versioned product key
  (admin Stripe bindings page from 002 holds the mapping); every configured Price
  amount, currency, interval, and lookup key must match version 1 exactly.

### Repeat for live mode (later, before rollout step "live payments")

- Same products/prices/portal/tax in live mode; separate webhook endpoint + secret;
  separate restricted key; bindings entered per environment. Test and live objects and
  secrets can never cross (livemode check above). Live tax registrations and final tax
  classification are rollout gates (010), not test-setup prerequisites.

## Exit criteria

- Test-mode account with all ten products/prices, portal configured with plan switching
  disabled, tax enabled with treatment recorded per product class.
- Restricted key stored in Render env and verified against the 007 call list; webhook
  endpoint + secret configured once 007's route is deployed.
- Every version-1 paid product has a test-environment Stripe binding recorded — 002 then
  publishes version 1, and environment activation/checkout is unblocked for 007.

## Amendments from phase 004 (2026-07-14)

- No scope changes — 004 (gateway metering/enforcement) touches nothing in
  Stripe account setup. Noted for the record: dunning's enforcement lever
  (`hosting_payment_due` at the gateway) already exists, so this phase's
  webhook/key scope needs no additions for it.
