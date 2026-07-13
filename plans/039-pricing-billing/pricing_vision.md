# Luna Credits — Pricing Vision

## Core idea

Luna has one internal currency called **credits**.

- **100 credits = $1.00**
- **1 credit = $0.01**
- Customers buy credits and then see all Luna activity priced only in credits.
- Credits are whole integers. No fractional credits are displayed or charged.
- Every charge comes from the account's shared credit balance.
- Lunas do not have separate wallets.

Dollars remain an internal input for converting Luna's vendor costs into credit charges.
After purchase, the customer experience is entirely credit-based.

## What credits pay for

The same credits pay for everything Luna provides:

- Monthly existence/hosting of each Luna.
- LLM calls.
- Chat messages and playbook execution.
- External service and plugin API calls.
- Forge, browser, code execution, storage, and other resource usage.
- One-time paid marketplace plugins.
- Future Luna services and resources.

Every charge appears in the account statement as an integer number of credits associated
with the Luna and action that consumed it.

## Account-level balance

Credits belong to the **account**, not a user or an individual Luna.

All Lunas in the account consume from the same balance:

```text
Account credit balance
├── Luna A usage
├── Luna B usage
└── Luna C usage
```

Account owners can still limit each Luna independently:

- Maximum credits per day.
- Maximum credits per month.

A Luna stops starting new paid actions when either its own limit or the account balance is
exhausted, even when another Luna in the account can still spend.

## Credit purchases

### Recurring monthly credit buckets

Customers subscribe to a monthly credit bucket. The payment automatically recurs and
grants a fresh balance each billing cycle.

Example buckets:

| Monthly payment | Paid credits | Bonus credits | Total |
|---|---:|---:|---:|
| $100 | 10,000 | 1,000 | 11,000 credits |
| $200 | 20,000 | 5,000 | 25,000 credits |

Recurring bucket credits:

- Are granted only after the recurring payment succeeds.
- Split into a **paid balance** and a **bonus balance**.
- Show both balances separately to the customer, alongside their total credits.
- Consume bonus credits before paid credits.
- Paid recurring credits expire at the end of that billing cycle and do not roll over.
- Bonus credits have their own independently configurable expiration policy.
- Are replaced by the next cycle's new recurring grant.
- May include a larger bonus at higher subscription levels.

Each bucket also has a yearly variant: no dollar discount (12× the monthly payment), with
the yearly incentive paid as extra credits into the gift bucket.

The exact bucket prices and bonuses are configurable products, not hardcoded billing
logic.

### One-time top-ups

When recurring credits run out, the customer can:

1. Buy a one-time top-up.
2. Upgrade to a larger recurring bucket.

Top-ups are sold at face value with no bonus:

| Top-up payment | Credits granted |
|---|---:|
| $10 | 1,000 credits |
| $100 | 10,000 credits |

Whether purchased top-up credits expire is a separate policy decision. They must remain a
separate grant lot from recurring credits so their expiration rules can differ.

### Free trial

There is no perpetual free tier. A new account receives a one-time trial gift of credits
valid for a limited period (default 28 days), sized to cover one basic Luna's first
hosting month plus activity. After the trial, the entry paid tier is a hobby bucket
(default $19/month for a basic agent).

Trial and promotional credits do not change resource prices. A trial account pays the
same number of credits for the same action as a paid account. The only difference is how
the credits were granted.

This keeps one pricing system:

```text
same action + same internal cost + same margin constant = same credit charge
```

## Luna existence charge

Each Luna costs **999 credits per month** for existence and hosting:

```text
999 credits = $9.99 of credit value per Luna per month
```

This charge applies even when the Luna is not used.

The charge is paid upfront for that Luna's monthly hosting period and attributed to that
Luna.

If the account later runs out of credits:

- The already-paid Luna server remains allocated until the end of its paid monthly period.
- The Luna cannot perform LLM calls, service calls, or other paid work.
- At the end of the paid period, the server is stopped.
- It cannot be restarted until the negative ledger balance is cleared and the next
  999-credit hosting period can be paid.

The exact billing anchor and proration for Lunas created or deleted mid-cycle remain to be
defined.

## LLM pricing

### Principle

Luna does not use percentage markup on LLM provider cost.

Percentage markup makes Luna's margin depend on the provider's price. It also punishes
optimization: when Luna lowers the provider cost, Luna's margin falls.

Instead, every LLM call has:

1. The actual provider cost.
2. A configurable fixed margin for that call category.

This keeps Luna aligned with customers:

- Provider prices fall → customer credit cost falls.
- Better routing or caching lowers cost → customer credit cost falls.
- Luna keeps the same fixed margin per call.

### Formula

```text
credits_to_charge =
    ceil((actual_llm_cost_usd + margin_constant_usd) / 0.01)
```

Equivalent form:

```text
credits_to_charge =
    ceil((actual_llm_cost_usd + margin_constant_usd) × 100)
```

`ceil` ensures the result is always a whole number of credits and never rounds below the
calculated charge.

Example:

```text
Actual LLM cost:       $0.037
Chat margin constant:  $0.020
Total internal price:  $0.057
Customer charge:       ceil(5.7) = 6 credits
```

The customer sees only:

```text
Chat LLM call: 6 credits
```

### Context-specific margin constants

Margin is selected by call context, not only by provider or model.

Initial examples:

- `llm.chat_call_margin`
- `llm.playbook_call_margin`
- `llm.background_call_margin`
- `llm.summarization_call_margin`
- `llm.forge_call_margin`
- `llm.other_call_margin`

More constants can be added without changing the credit system.

The charge record must preserve:

- Which Luna made the call.
- The call context/category.
- Provider and model.
- Actual provider usage and internal cost.
- Margin constant and version applied.
- Final integer credit charge.

Customers see the action and credits charged. Internal vendor cost and margin remain
operator-only data.

### Price changes

Margin constants are versioned and effective-dated.

Changing a constant affects future calls only. Past calls keep the exact cost, constant,
and credit calculation used at the time.

## Other resource pricing

Every resource has an internal pricing rule that produces an integer credit charge.

Depending on the resource, that rule may be:

- Fixed credits per action.
- Vendor cost plus a fixed margin constant.
- Credits per minute/hour/day.
- Credits per GB or operation.
- One-time fixed marketplace price.
- Monthly fixed service charge.

Percentage-of-vendor-cost margin is not the default.

Examples:

```text
External API call:
ceil((vendor_cost_usd + service_call_margin_usd) × 100)

Browser session:
fixed_start_credits + credits_per_minute

Marketplace plugin:
fixed one-time integer credit price

Luna hosting:
999 credits per billing month
```

All formulas and constants belong in a versioned price book editable by an administrator.

## Balances and spending order

The customer sees the total account balance and its separate parts:

- Bonus credits.
- Paid recurring credits.
- Purchased top-up credits.
- Free/promotional credits, when present.

Each balance is backed by separate grant lots, so it can have its own source, expiration,
and refund policy.

Recommended spending order:

1. Bonus credits.
2. Other free/promotional credits that expire first.
3. Paid recurring credits that expire first.
4. Purchased top-up credits.

This minimizes avoidable expiration while preserving each grant's source and policy.

The UI shows the total available balance, the separate balances, and the expiration date
for each expiring balance.

## Limits and enforcement

The account balance is allowed to become negative. A completed transaction always posts
its full integer charge; it is never reduced to the credits remaining.

Example:

```text
Starting account balance:   5 credits
Completed transaction:     10 credits
New account balance:       -5 credits
```

The `-5` balance is shown in red. As soon as the account balance is zero or negative:

- All LLM calls are blocked across every Luna in the account.
- All external service calls and other paid actions are blocked.
- No new paid resource or Luna can be created.
- Already-paid Luna servers remain allocated but inactive until their paid hosting period
  ends.

An action that was already in progress may finish and post its complete charge, which can
push the balance below zero. This deliberately allows bounded overrun instead of losing
the final provider charge.

Any new credit grant or top-up first repays the negative balance. Paid activity resumes
only after the account has a positive balance. A stopped Luna also requires its next
999-credit hosting period to be paid before it can restart.

Limits are measured in credits:

```text
Account balance:            25,000 credits
Luna A daily limit:          2,000 credits
Luna A monthly limit:       15,000 credits
Luna B daily limit:          5,000 credits
```

An account owner can lower limits at any time. Limit changes do not rewrite past usage.
Crossing a Luna's daily or monthly limit blocks that Luna's new paid actions even when the
shared account balance remains positive.

## Customer experience

The customer-facing system uses credits consistently:

- Pricing page: monthly payment → monthly credits.
- Dashboard: total account credits plus separate bonus, recurring, top-up, and
  free/promotional balances.
- Luna card/detail: credits used today and this month.
- Action history: action → integer credits charged.
- Limits: credits per day/month.
- Low/negative balance: credits remaining or debt shown in red.
- Marketplace: plugin price in credits.
- Hosting: 999 credits per Luna per month.

Provider token prices, vendor invoices, dollar cost, and margin constants are internal.

## Internal financial view

Operators need both sides for every charge:

- Credits charged to the customer.
- Customer credit value in dollars.
- Actual vendor cost.
- Fixed margin constant.
- Rounding difference.
- Realized gross margin.

This supports cost reconciliation without exposing provider economics to customers.

## Stripe's role

Stripe handles:

- Recurring monthly bucket payments.
- One-time top-ups.
- Payment methods.
- Failed payments and retries.
- Refunds, disputes, tax, invoices, and receipts.

Luna's own ledger handles:

- Credit grants.
- Expiration.
- Shared account balance.
- Reservations and charges.
- Per-Luna limits.
- Credit history.

Stripe payment success creates a credit grant exactly once. Browser redirects never grant
credits; only verified, idempotent Stripe webhook processing does.

## Non-negotiable invariants

- One credit is always worth $0.01.
- All customer charges are integer credits.
- Credits belong to the account and are shared by its Lunas.
- Every charge is attributed to one Luna and action.
- LLM margin is a configurable fixed constant per call context, not a percentage.
- Bonus and paid credits are separate customer-visible balances; bonus credits are
  consumed first.
- Paid recurring credits expire at the cycle boundary and do not roll over.
- Bonus credits have an independently configurable expiration policy.
- Top-ups receive no volume bonus.
- Free credits do not alter resource pricing.
- Each Luna can have independent daily and monthly credit limits.
- The account balance may become negative when a completed action costs more than the
  remaining credits; the full charge is always recorded.
- A zero or negative account balance blocks all new LLM and paid service activity.
- Already-paid Luna hosting continues until the end of its monthly period, then the Luna
  stops until the debt and next hosting period are paid.
- Past charges never change when provider costs or margin constants change.

## Decisions still TBD

- Complete recurring bucket catalog and bonuses.
- Free daily/monthly grant size.
- Top-up credit expiration policy.
- Exact LLM margin constants by context.
- Constants and formulas for non-LLM resources.
- Hosting proration and deletion policy.
- Maximum permitted in-flight exposure from concurrent LLM/tool executions.
- Refund and marketplace seller-payout policy.
