# 039 — Luna Credits, pricing, metering, and billing

**Status:** Detailed implementation plan; not started  
**Vision:** `plans/039-pricing-billing/pricing_vision.md`  
**Research:** `plans/039-pricing-billing/RESEARCH.md`  
**Luna dependency:** `plans/039-pricing-billing/luna-core-plan.md`

## Goal

Build one account-level Luna Credits system in which every platform-funded action is
measured, priced by immutable commercial and provider-cost versions, and charged as whole
credits.

Customers see only credits:

- `100 credits = $1.00`
- `1 credit = $0.01`
- one shared account balance;
- separate visible bonus, recurring paid, top-up, free, and gift balances;
- per-Luna daily and monthly limits;
- an action-by-action usage statement;
- a red negative balance and an exact explanation when spending is blocked.

Operators additionally see actual vendor cost, credits charged, cash basis, fixed margin,
rounding, reconciliation state, and both versions used.

## Non-negotiable product rules

1. One credit always represents $0.01 of customer value.
2. All customer-facing prices and charges are integer credits.
3. Credits belong to `Account`; Lunas spend from the account's shared balance.
4. Every charge identifies one Luna, one root action, and one service/SKU.
5. LLM price is:

   ```text
   ceil((actual provider cost USD + fixed context margin USD) × 100)
   ```

6. The fixed margin is selected by call context, not by a percentage markup.
7. Past charges never change when costs, formulas, or constants change.
8. Recurring paid and recurring bonus credits are separate customer-visible balances.
9. Bonus credits are consumed before recurring paid credits.
10. Paid recurring credits expire at their cycle boundary.
11. Bonus expiration is independently configurable.
12. One-time top-ups have no bonus.
13. There is no perpetual free tier: new accounts get a one-time 28-day trial gift.
    Trial and promotional credits do not receive cheaper resource prices.
14. Each Luna is charged 999 credits upfront for each hosting month.
15. A completed in-flight action posts its full charge even when this makes the balance
    negative.
16. A zero or negative balance blocks every new paid action account-wide.
17. An already-paid Luna remains allocated until its hosting period ends, but cannot
    start paid work while the account is blocked.
18. Hosting renewal is a known upfront charge and must not create debt: it requires the
    debt to be cleared and at least 999 spendable credits.
19. Stripe collects money; Luna's own ledger owns credits, expiration, limits, and usage.
20. Published commercial/provider-cost versions and posted financial records are
    immutable.

## Scope

### Included

- Immutable Luna Credits ledger and grant lots.
- Recurring paid/bonus buckets, one-time top-ups, trial signup gifts, and gifts.
- Pricing-version drafts, simulation, publication, assignment, history, and rollback.
- Billing-grade LLM, service, hosting, storage, job, and marketplace metering.
- Atomic pre-action enforcement with bounded in-flight debt.
- Per-Luna daily/monthly credit limits.
- Monthly per-Luna hosting periods and renewal enforcement.
- Stripe subscriptions, top-ups, tax, invoices, refunds, disputes, and portal.
- Customer balance, usage, limits, top-up, and billing UI.
- Admin pricing management, margin simulator, ledger operations, and reconciliation.
- Platform-owned one-time marketplace purchases.
- A companion plan for the smallest generally useful Luna core changes.

### Not included in the first launch

- Multi-currency or changing the value of one credit.
- Customer-visible dollars after credits have been purchased.
- Percentage LLM markup.
- Using Stripe Billing Credits as Luna's runtime wallet.
- Trusting Luna, a browser, a plugin, or a client-supplied usage amount.
- Exact attribution of inherently shared Render/Postgres costs unless a published SKU
  allocates them.
- Third-party seller payouts until Stripe/legal approval is complete.
- Editing the `luna/` submodule as part of this plan.

## Decisions and defaults

All defaults below are seeded in commercial pricing version 1 and remain
admin-configurable by creating a new commercial version. The fixed credit value is the
only non-editable field.

### Default customer products

| Product | Payment | Paid credits | Bonus/gift credits | Expiration |
|---|---:|---:|---:|---|
| Free trial (signup gift) | $0 | 0 | 1,800 gift credits | 28 days |
| Hobby 19 | $19/month | 1,900 | 0 | End of paid cycle |
| Recurring 100 | $100/month | 10,000 | 1,000 bonus | End of paid cycle |
| Recurring 200 | $200/month | 20,000 | 5,000 bonus | End of paid cycle |
| Hobby 19 yearly | $228/year | 22,800 (1,900/mo lots) | 1,900 yearly gift | Paid lots monthly; gift end of yearly cycle |
| Recurring 100 yearly | $1,200/year | 120,000 (10,000/mo lots) | 12,000 bonus (1,000/mo) + 10,000 yearly gift | Bonus monthly; gift end of yearly cycle |
| Recurring 200 yearly | $2,400/year | 240,000 (20,000/mo lots) | 60,000 bonus (5,000/mo) + 20,000 yearly gift | Bonus monthly; gift end of yearly cycle |
| Top-up 10 | $10 once | 1,000 | 0 | No expiration |
| Top-up 25 | $25 once | 2,500 | 0 | No expiration |
| Top-up 50 | $50 once | 5,000 | 0 | No expiration |
| Top-up 100 | $100 once | 10,000 | 0 | No expiration |

There is no perpetual free tier. A new account receives the one-time 28-day trial gift,
which deliberately covers one 999-credit basic Luna hosting period plus roughly 800
credits of activity. When trial credits are exhausted or expire, the account is blocked;
the Luna stops at the end of its already-paid hosting month unless the account subscribes
or tops up. Hobby 19 is the entry paid tier: 1,900 credits funds one basic Luna's
hosting plus ~900 credits of monthly activity. Trial and Hobby accounts default to one
active Luna. All these values can be changed in a later version after margin simulation.

Yearly buckets carry no dollar discount: the price is exactly 12× the monthly payment and
paid credits still equal payment × 100 in total. The yearly incentive is extra credits in
the gift bucket — the default is one month's paid credits, granted once, valid until the
end of the yearly cycle. One verified yearly invoice creates twelve scheduled monthly
paid lots (each effective at its month start and expiring at its month boundary, using
the grant `scheduled` status), the monthly bonus lots where the bucket has a bonus, and
the single yearly gift lot. Monthly pacing and expiration therefore behave identically on
monthly and yearly plans. A refund of a yearly invoice cancels the not-yet-effective
scheduled lots and reverses the rest under the normal reversal rules. Yearly gift sizes
are launch assumptions to validate in the simulator.

### Default balance behavior

- Burn order:
  1. recurring bonus, earliest expiry first;
  2. gifts/promotions/free credits, earliest expiry first;
  3. recurring paid credits, earliest expiry first;
  4. non-expiring top-ups, oldest first.
- Top-ups do not expire.
- Admin gifts default to 90-day expiration, but the issuer must see and may change the
  exact expiration before confirming.
- Paid actions are blocked when posted balance is `<= 0`.
- A new grant first clears debt. Spending resumes only when posted balance is positive.
- A hold reduces authorization availability but does not change the displayed posted
  balance.
- At most one uncovered in-flight overrun is permitted per account, capped at 1,000
  estimated credits by default. Additional concurrent work requires positive
  authorization availability.

This preserves the required `5 credits → 10-credit completed action → -5 credits`
behavior without allowing unlimited concurrent debt.

### Default LLM constants

The margin classification below is internal cost machinery. It is never
customer-visible: it does not appear in usage metrics, statements, or API responses, and
it is never exposed to the Luna agent. Customers see integer credits per action and
functional breakdowns (chat, playbook runs, per-Luna, per-service) derived from
root-action metadata, not from this classification.

There are three LLM contexts:

- `agent` — any agentic loop: chat turns, playbook agent steps, background/autonomous
  runs, tool loops.
- `direct` — single one-shot LLM calls: playbook `llm_step`, UI one-shots, utility calls,
  summarization/condensation.
- `forge` — coding-agent calls inside a Forge job.

`agent` and `direct` constants are split by model tier: `top` (Opus/Fable-class models,
listed explicitly in the version config) and `mid` (all other models). The gateway
verifies model tier from the requested model and `forge` from the job-scoped token; only
agent-versus-direct is tenant-declared, and anything unclassified rates as `agent`, the
most expensive non-forge context.

The initial values are launch assumptions to validate in the simulator, not permanent
economics:

| Context | Top-tier model | Mid-tier model |
|---|---:|---:|
| `agent` | $0.020 | $0.010 |
| `direct` | $0.010 | $0.005 |
| `forge` | $0.050 | $0.050 |

- A logical call is one request by Luna for a model result. Provider retries/fallback
  attempts belong to that logical call and never multiply the fixed margin.
- A chat action may contain multiple logical calls around tool execution; each logical
  call is charged and all are grouped under the same root action.
- Provider-billable fallback-attempt costs are summed into the logical call; the fixed
  context margin is added once and `ceil` is applied once.
- Chargeability is defined gateway-side (resolves review H3): a call is
  customer-chargeable once the gateway has initiated accepted provider work and receives
  a successful billable response or billable usage. Tenant cancellation, disconnect,
  timeout, or discarding the result never converts provider spend into Luna-absorbed
  cost. Only provider/platform failures that produce no usable provider result are
  Luna-absorbed, with no customer margin charged.
- Unknown/unverifiable context rates as `agent` at the call's verified model tier, never
  a cheaper client-provided value.
- Enabled models and services with no valid pricing rule fail closed in enforcement mode.

Version 1 seeds the SKU catalog with the LLM contexts and hosting above. Non-LLM service
SKUs (search, browser, Composio, storage, jobs, marketplace) are seeded in the catalog
but disabled until each receives a defined price; disabled SKUs fail closed in
enforcement mode.

Forge (plan 034) is not operational yet. When it ships, a forge job is priced as two
SKUs: forge machine time (credits per machine-minute with its own constant, since the
forge runs on a dedicated larger Fly machine) plus its LLM calls at the `forge` context
constant. Both SKUs are seeded disabled in version 1.

### Default hosting and limit behavior

- Hosting: 999 credits per Luna, paid before each Luna-specific monthly period. 999 is
  the basic Luna server tier; larger server tiers with higher hosting prices are future
  versioned products, which is why hosting is a credit price rather than a constant.
- First hosting period begins when provisioning succeeds.
- No first-launch proration and no refund for early deletion by default.
- Renewal uses the Luna's original monthly anchor with normal calendar-month arithmetic.
- If renewal cannot collect exactly 999 credits, stop the Luna at period end and mark it
  `payment_due`.
- Paid accounts have no per-Luna cap until the owner sets one.
- Trial Lunas default to 75 credits/day and 800 credits/month of consumption.
- Daily and monthly limit periods are UTC calendar periods; the UI shows the exact reset
  timestamp.
- Per-Luna limits measure consumption on top of the hosting base price: hosting charges
  do not count toward the daily or monthly limit. Hosting is constrained only by the
  account balance and renewal rules.

## Financial architecture

### Sources of truth

There are four distinct layers:

```text
Raw billable event
    ↓ immutable provider/resource facts
Rated charge
    ↓ immutable pricing-version calculation
Credit ledger transaction
    ↓ immutable customer balance movement
Read projections and rollups
    ↓ rebuildable UI/query acceleration
```

- `billable_events` answers what happened and what Luna actually paid.
- `rated_charges` answers how that event became an integer credit charge.
- the credit ledger answers why the customer's balance changed.
- Stripe records money collected, not runtime credit availability.
- legacy `usage_events` remains telemetry during migration and is never treated as money.

### Integer units

- Customer ledger and limits use signed integer credits.
- Vendor cost, margin constants, rounding, Stripe amounts, and cash basis use integer
  micro-USD.
- No financial path uses `float`.
- The fixed conversion is `1 credit = 10,000 micro-USD`.
- Rating performs all arithmetic in integers and applies `ceil` once to the final call
  amount.

### Required database entities

#### Pricing

`commercial_pricing_versions`

- `id`, monotonic `version_number`, `name`, `status`
  (`draft|published|retired`);
- `parent_version_id`;
- validated immutable `config_json`;
- `config_schema_version`, `config_hash`;
- `notes`, `created_by`, `created_at`, `published_at`.

`commercial_pricing_assignments`

- `account_id`, `commercial_pricing_version_id`;
- `effective_at`, optional `ends_at`;
- source (`new_account_default|global_rollout|manual_test|migration`);
- actor and audit reference.

`commercial_pricing_rollouts`

- version, audience (`new_accounts|all_accounts|selected_accounts`);
- effective timestamp, commercial migration policy, status;
- counts for scheduled/applied/failed account assignments.

`provider_cost_versions`, `provider_cost_rates`

- global effective-dated versions of Luna's real provider tariffs;
- provider, canonical model/service SKU, region/tier, and native unit;
- exact integer/rational micro-USD rate and provenance;
- status/quality (`estimated|provider_confirmed|reconciled`);
- no account audience: a provider tariff change applies globally at its effective time.

Every account receives an explicit assignment. A charge never asks for a mutable
"current version"; authorization snapshots both the account's commercial version and
the globally effective provider-cost version. Settlement uses those snapshots even if a
publication occurs mid-stream.

Provider-cost versions are intentionally separate from commercial versions. Otherwise a
customer retained on old margins would also be incorrectly retained on Luna's old vendor
cost after a provider changed its tariff.

#### Account wallet and grants

`billing_accounts`

- one row per `Account`;
- posted signed balance, open exposure, debt state, billing status;
- pricing assignment pointer and projection version;
- Stripe customer pointer and optional auto-top-up settings.

`credit_grants`

- account, source type
  (`subscription_paid|subscription_bonus|topup|free_recurring|gift|refund|admin`);
- original and remaining integer credits;
- effective and expiration timestamps;
- visible balance category;
- burn priority;
- Stripe invoice/payment or admin source reference;
- cash paid and cash-basis micro-USD per granted credit;
- status (`scheduled|active|exhausted|expired|reversed`).

`credit_ledger_transactions`

- immutable transaction header;
- type (`grant|charge|expiration|refund|reversal|adjustment|debt_repayment`);
- unique idempotency key;
- account, optional Luna/root-action/service;
- source reference, reversal reference, commercial/provider-cost versions where
  applicable;
- reason, actor, timestamps, metadata without prompts or secrets.

`credit_ledger_postings`

- transaction, ledger account, signed integer credits;
- database-enforced sum of zero for each posted transaction;
- no update/delete after posting.

`credit_consumptions`

- charge transaction → grant lot allocations;
- credits consumed per grant;
- uncovered amount that became debt;
- enough information to reverse into the same lots or a refund lot.

`account_balance_projections`

- posted total and balances by visible category;
- open held/exposure credits;
- next expirations;
- sequence/version used to detect stale writes;
- always rebuildable from ledger + grant allocations.

#### Holds, limits, and periods

`billing_holds`

- unique operation/logical-call ID;
- account, Luna, root action, service/SKU, commercial/provider-cost version snapshots;
- estimated credits and uncovered-overrun amount;
- status (`open|settled|released|expired|needs_reconciliation`);
- authorization, expiry, settlement, and release timestamps.

`agent_credit_limits`

- nullable daily/monthly limits;
- warning thresholds;
- who changed the limit and when.

`agent_limit_periods`

- Luna, period kind/start/end;
- settled credits, open exposure, last ledger sequence;
- unique period key for atomic updates.

`agent_hosting_periods`

- Luna, start/end, price/version;
- charge transaction and resource allocation references;
- state (`pending|paid|active|ended|payment_due|stopped`);
- unique Luna + period start.

#### Metering and rating

`billable_events`

- unique source idempotency key and call/operation ID;
- account, Luna, root action, job, plugin, service, SKU;
- context (`agent|direct|forge`) and verified model tier;
- root-action type (chat, playbook run, scheduled/background run, forge job) for
  customer-facing functional grouping;
- provider/model/request/response IDs and attempt number;
- native quantity JSON;
- integer vendor cost micro-USD and cost source
  (`provider_usage|catalog|reconciled|estimated`);
- status and event time;
- no prompt, completion, tool arguments, credential, or personal content.

`rated_charges`

- logical call/action, event-attempt, and hold references;
- commercial and provider-cost version IDs plus full rule snapshots;
- vendor cost, fixed margin, rounding, final integer credits;
- customer-charge status and ledger transaction;
- separate Luna-absorbed vendor cost for failed attempts.

`resource_allocations`

- Luna/resource/provider/SKU;
- provider resource ID and dimensions;
- opened/closed timestamps;
- last accrued boundary and reconciliation state.

`usage_rollups`

- day/account/Luna/service/context/model;
- calls, quantities, credits, vendor cost, estimated/reconciled counts;
- rebuildable and never used as the financial source of truth.

#### Stripe and durable work

`billing_subscriptions`, `billing_payments`, `billing_invoices`

- local projections of canonical Stripe objects;
- product/version mapping and cycle boundaries;
- no secret card data.

`processed_webhooks`

- provider event ID unique;
- raw event type/object IDs, processing state, attempts, error, timestamps.

`billing_outbox`

- durable post-commit jobs for webhooks, grants, expiration, hosting renewal,
  reconciliation, rollups, notices, and Stripe sync.

`pricing_simulations`

- actor, time/filter inputs, baseline/candidate commercial version IDs, and provider-cost
  basis/cutoff;
- scenario transforms, immutable config hashes;
- state and saved aggregate result.

### Database requirements

- Introduce a real migration tool before creating billing tables. Financial schema must
  not be added through `Base.metadata.create_all()` or lifespan `ALTER TABLE`.
- Add database constraints/triggers for balanced postings, immutable published versions,
  immutable posted transactions, nonnegative grant remainder, valid expiration, and
  unique idempotency.
- Use row locks plus projection sequence checks for authorization and settlement.
- External network calls never occur while a database transaction is open.
- Every external side effect uses an outbox or an idempotent recovery record.

## Pricing version model

### Commercial version contents

One account-assigned commercial version snapshot contains:

- fixed credit value metadata (read-only);
- all LLM contexts, model tier lists (top/mid), and fixed margin constants;
- non-LLM service SKU formulas and constants;
- hosting price and period policy;
- recurring products and paid/bonus grants;
- trial signup gift rules;
- gift defaults;
- one-time top-up steps;
- grant expiration and burn order;
- default account/Luna warning and hard-limit policies;
- in-flight exposure policy;
- marketplace platform-owned prices;
- enabled/disabled launch state for each billable SKU;
- simulator defaults.

The billable SKU catalog is a dynamic JSON list inside the version's `config_json`, not
a fixed schema: each entry carries the SKU key, service, formula type, constants, and
enabled state. Adding, pricing, or disabling a SKU means cloning a draft and editing this
list; no database schema change is required.

Stripe IDs are environment bindings to a versioned product key, not portable values in
the pricing formula itself.

### Provider-cost version contents

A separate global provider-cost version contains:

- provider, canonical model/service SKU, region/tier, and native billing unit;
- normal/cached/cache-write input, output/reasoning, embeddings, audio/image, searches,
  minutes, GB-hours, and other provider-native dimensions;
- exact rate numerator/denominator in micro-USD;
- effective timestamp, source/provenance, and data-quality status.

Provider-cost versions are immutable and effective-dated but are not assigned by customer
cohort. Provider tariff changes affect Luna's actual cost globally. A provider response
that supplies authoritative monetary cost may be stored directly while retaining the
cost-version/rule used for validation and simulation.

### Admin workflow

1. Clone an existing published commercial version into a draft.
2. Edit the draft. Saving updates the draft only.
3. Validate:
   - credit value is unchanged;
   - paid credits exactly equal payment × 100;
   - top-ups have no bonus;
   - every enabled service/model has a complete nonnegative rule;
   - every context has a fixed constant;
   - burn/expiration policies are deterministic;
   - publication validates portable product keys and economics only — Stripe IDs are
     environment bindings, and missing bindings block environment activation, checkout,
     and live promotion, not publication (avoids the 002↔006 circular dependency);
   - no rule permits unbounded in-flight exposure.
4. Run the margin simulator and save one or more reports against the draft.
5. Publish. Publication freezes the commercial JSON and hash permanently.
6. Promote with one audience:
   - `new_accounts`: becomes the assignment for accounts created after `effective_at`;
   - `all_accounts`: schedules a new assignment for all accounts at `effective_at`;
   - `selected_accounts`: internal/canary accounts only.
7. Audit the rollout and failures.

Changing a published commercial version means cloning it. "Rollback" schedules a prior
published commercial version as a new future assignment; it never edits historical
assignments or charges. Provider-cost changes use a separate global publish/effective
workflow and can never be rolled out to only new customers.

### Subscription behavior during rollouts

- Runtime usage prices switch at the assignment's effective timestamp.
- Existing subscription grants already issued keep their original amount and expiration.
- For `new_accounts`, existing Stripe subscriptions are untouched.
- For `all_accounts`, changed recurring products migrate at each account's next renewal,
  never by silently rewriting the current paid cycle.
- Upgrades start a new billing cycle immediately after successful payment and issue the
  new bucket once.
- Downgrades take effect on the next renewal.
- A pricing rollout is not complete until both usage assignments and required Stripe
  renewal migrations are visible in the admin status.

## Credit grant behavior

### Recurring paid and bonus grants

On a verified paid Stripe invoice:

1. Resolve the subscription product key and the version assigned to that renewal.
2. Create one `subscription_paid` grant and one `subscription_bonus` grant with the same
   invoice period.
3. Both grants use the invoice ID in their idempotency key.
4. Show them separately and include both in total available credits.
5. Consume bonus first.
6. Expire each grant according to its own policy at period end.
7. Never "replace" by updating a balance; the next invoice creates new grant lots.

### Trial and gift grants

- Account creation creates the configured trial signup gift exactly once.
- There is no recurring free grant. When trial credits expire or run out, the account is
  blocked until it subscribes or tops up; the Luna stops at the end of its already-paid
  hosting month.
- Trial gift amount, trial length, active-Luna maximum, and expiration come from the
  account's commercial pricing version.
- Gifts are explicit grant lots with issuer, reason, amount, and expiration.
- Admin gift creation requires a reason and confirmation preview.
- Trial/gift credits pay the same SKU prices as purchased credits.

### Top-ups

- The customer chooses a configured step; the browser cannot submit an arbitrary credit
  amount.
- The server creates Stripe Checkout/PaymentIntent metadata from the selected versioned
  product.
- Only a verified successful payment webhook creates the top-up grant.
- Top-up grants have no bonus and are non-expiring by default.
- If the balance is negative, the grant first repays the debt in the displayed total;
  only the positive remainder becomes spendable.

### Expiration and reversals

- Expiration is an append-only ledger transaction, never deletion.
- Expiry workers lock and consume only the grant's remaining credits.
- Re-running the worker is idempotent.
- Refunds/disputes reverse the matching unconsumed credits first.
- If refunded credits were already consumed, the full reversal posts and may create a
  negative account balance.
- Manual corrections use reversal + replacement, never record edits.

## Billing and enforcement path

### One internal service interface

Every paid boundary calls a single server-side billing service:

```text
authorize(operation_id, account_id, luna_id, sku, estimate, metadata) -> hold | block
record_event(source_id, hold_id, dimensions, native_usage, vendor_cost) -> event
rate(event_id, pricing_version_id) -> rated_charge
settle(operation_id, rated_charge_id) -> ledger transaction + released remainder
release(operation_id, reason)
grant(source_id, account_id, category, credits, effective_at, expires_at)
reverse(transaction_id, reason)
balance(account_id) -> posted, exposed, category balances, debt state
```

Authorization atomically checks:

- posted account balance is positive;
- no account debt block;
- account spendable balance after open exposure;
- uncovered in-flight overrun policy;
- Luna daily and monthly settled + held usage;
- product/SKU is enabled and priced;
- pricing assignment exists;
- resource/hosting-specific prerequisites.

Settlement always posts the complete real charge. It may exceed the hold and may make the
balance or Luna period negative. That blocks later work but does not discard provider
cost.

### Why users cannot bypass the charge

- Real platform provider keys stay only in the control-plane gateway.
- A Luna receives only an agent-scoped, revocable gateway token.
- The gateway resolves account/Luna from that token; it never trusts IDs in the body.
- Authorization occurs in the control plane before forwarding to a paid upstream.
- Actual usage comes from the upstream response/provider reconciliation, not Luna.
- The ledger, pricing assignment, limit counters, and Stripe webhook processing are not
  writable by tenant APIs.
- Non-LLM services use the same proxy or a signed idempotent server-to-server callback.
- Machine/Volume/hosting events are produced by the control-plane runtime boundary.
- Unknown platform-funded service paths fail closed in enforcement mode.
- No platform key may be injected directly into a hosted Luna for an enforced service.
- Migrate or disable existing `key_mode=env` and `LEGACY_REAL_KEY_VARS` paths before
  enforcement; a real key on the tenant machine is an unmeterable bypass.
- Billing authorization reads fresh ledger/limit rows and never relies on the existing
  short-lived auth/account cache.

The tenant process is not a trusted billing authority. Model tier is verified by the
gateway from the requested model, and `forge` is verified from the job-scoped token —
neither can be spoofed. The only tenant-declared distinction is `agent` versus `direct`,
carried in an advisory header; a missing, invalid, or unknown declaration rates as
`agent`, the most expensive non-forge context, so stripping metadata never lowers a
price. At launch a claimed `direct` context is accepted as declared: the worst-case
leakage is the agent/direct constant spread per call ($0.01 top tier), which is bounded
and visible in reconciliation. Signed run envelopes are deferred to a later hardening
step and are only needed if that leakage proves material.

There is one unavoidable limit: code running inside a tenant cannot be remotely proven
to be a "real single-shot call" without a trusted execution boundary. Therefore context
pricing must never be the only cost-recovery control. Unknown calls use the most
expensive default, all contexts remain above an operator-defined safety floor, and the
verified dimensions (model tier, forge token, service identity) carry most of the price
variance.

### Gateway LLM flow

1. Authenticate the tenant token and resolve account/Luna.
2. Resolve context: `forge` from the job-scoped token; otherwise the advisory
   agent/direct header, defaulting to `agent` when absent or invalid. Resolve model tier
   from the requested model.
3. Resolve canonical model, commercial assignment, and global provider-cost version.
4. Estimate worst-case credit exposure from model limits and fixed context margin.
5. Authorize hold; return a machine-readable block before contacting the provider.
6. Proxy while capturing logical-call ID, attempt ID, provider request ID, and native
   usage frames.
7. Persist one event per provider attempt under the logical call.
8. Calculate actual provider cost in micro-USD using provider-native dimensions and the
   snapshotted global cost version.
9. Sum billable attempt costs, apply the commercial context margin once, and rate the
   logical call with one final ceiling.
10. Settle the complete integer charge and release unused hold.
11. If no usable logical result was produced, mark all attempt cost as Luna-absorbed and
    release the customer hold after reconciliation.
12. If the stream disconnects after provider spend, preserve the operation for
    reconciliation; never silently release a possibly spent hold.

Provider adapters must cover normal/cached input, cache creation, output/reasoning,
audio/image, embeddings, service tiers, batch discounts, and future native dimensions
without double counting provider-defined totals.

### Non-LLM enforcement

- Gateway services: hold before proxy, rate from provider response or versioned
  fixed-per-action SKU.
- Forge/browser/code jobs: authorize a job envelope before launch, attach all child
  events to it, stop creating new child work at the cap, settle actual usage. Forge jobs
  additionally accrue the forge machine-time SKU for the machine's lifetime.
- Scheduler/WhatsApp/relays: signed callbacks with source idempotency; immediate precheck
  where Luna funds the action.
- Storage: periodic byte/operation snapshots and idempotent interval accrual.
- Fly Machines/Volumes: lifecycle allocation records and periodic accrual.
- Marketplace: exact-price authorization and atomic purchase/entitlement.
- Shared infrastructure: charge only a published fixed/included SKU; do not invent
  per-account precision from an invoice after the fact.

## Luna hosting lifecycle

### Creation

1. Require a positive account balance and exact 999-credit hosting authorization.
2. Provision the Luna.
3. When the required runtime resources are confirmed, create the hosting period and
   settle 999 credits.
4. On clean failure, release the hold.
5. If partial resources exist, retain a reconciliation item until cleanup is confirmed.

### During the paid period

- The allocation remains until period end even if the account later becomes negative.
- While blocked, the Luna may serve already-stored UI/history, but no LLM, paid service,
  job, new resource, or start/restart action is authorized.
- The hosting charge is not refunded because usage stopped.

### Renewal and recovery

1. Notify before renewal if the account cannot cover 999 credits.
2. At period end, attempt exact authorization.
3. If successful, settle and open the next period.
4. If unsuccessful, stop the runtime and mark `payment_due`; keep data according to the
   storage-retention policy.
5. A top-up first clears debt.
6. Restart requires positive balance plus a new 999-credit hosting payment.
7. Provider reconciliation confirms stopped resources are actually stopped; a failed
   stop remains an operator-visible cost leak.

## Stripe implementation

### Stripe objects

- One Stripe Customer per Luna `Account`.
- One Stripe Product/Price per published recurring bucket and environment.
- One server-defined one-time Price per top-up step.
- Subscription metadata stores Luna account, product key, and commercial pricing version.
- Top-up metadata stores Luna account, versioned step key, expected credits, and an
  unguessable server operation ID.
- Stripe Tax and tax codes are configured before live payments.

### Customer flows

- Start/upgrade recurring bucket with Stripe Checkout.
- Manage payment method, invoices, cancellation, and scheduled downgrade in Billing
  Portal.
- Buy a one-time top-up from fixed server-returned steps.
- Optional auto-top-up is off by default and requires an explicit threshold, step, saved
  payment method, and monthly cash cap.

### Webhook rules

- Verify the signature from the raw request body.
- Persist/dedupe the Stripe event before doing work.
- Retrieve canonical Stripe objects when delivery is out of order.
- Grant subscription credits from `invoice.paid`.
- Grant top-up credits from the confirmed successful PaymentIntent/Checkout payment.
- Never grant from `success_url`, browser state, or `checkout.session.completed` when
  payment is not final.
- Refund, dispute, chargeback, failed renewal, later success, cancellation, and reversal
  each have idempotent handlers.
- Failed renewal creates no new grants; existing grants keep their existing expiration.
- Webhook processing and grants use a durable outbox with retry/dead-letter visibility.

### Upgrade/downgrade defaults

- Upgrade: charge the newly selected full bucket and reset the billing anchor when payment
  succeeds; grant the full new paid + bonus lots once.
- Any still-valid old grants keep their original expiry; do not mutate them.
- Downgrade/cancel: apply at next renewal.
- No credit is issued for Stripe proration until the corresponding invoice is paid.

## Customer experience

### Navigation

Add `/dashboard/billing` and a visible `Credits & usage` entry from the dashboard header.
Agent cards link directly to filtered Luna usage. `AgentDetail` replaces the current
"Spend — coming soon" card with real data and controls.

### Account credits page

Show:

- total posted balance, red when zero/negative;
- open/held exposure separately;
- bonus, recurring paid, top-up, free, and gift balances;
- exact expirations and "use next" order;
- current recurring bucket and renewal date;
- top-up steps and upgrade action;
- low-credit/debt/failed-payment notices;
- invoices and receipts via Stripe;
- no vendor cost, dollar margin, provider price, internal constant, pricing context, or
  model-tier classification.

### Usage dashboard

Default range is 28 days, with today, 7 days, 28 days, and custom ranges.

Summary:

- credits used and remaining;
- credits used today/current month;
- upcoming expiration;
- per-Luna usage and limit progress;
- usage trend and projected depletion date clearly labeled as an estimate.

Breakdowns:

- Luna;
- service category (`hosting|llm|external_service|forge|browser|code|storage|marketplace`);
- service/plugin;
- action type (chat, playbook run, scheduled/background run, forge job) from root-action
  metadata — functional dimensions the customer can act on, never the internal pricing
  context;
- model for user-recognizable model selection;
- root action.

Action statement:

- time, Luna, human label, service, status, integer credits;
- expandable child events for multi-call chat/playbook/job actions;
- commercial/provider-cost versions and estimation/reconciliation indicator;
- running balance after the posted transaction;
- filters and CSV export.

The customer never sees internal USD, the agent/direct/forge pricing context, or the
model-tier classification. Provider token dimensions may be shown only when they help
explain usage and do not expose hidden pricing/margin.

### Luna limits

The account owner can set nullable daily and monthly credit limits per Luna.

- Show settled + open exposure, reset timestamp, warning threshold, and hard cap.
- Lowering a cap below current usage blocks new actions immediately; it does not reverse
  history.
- Raising a cap takes effect immediately and is audited.
- One Luna hitting its cap does not block another Luna while the account remains positive.
- Non-owner members may view usage but cannot change billing, payment, or limits.

### Machine-readable block contract

All surfaces return a stable code and safe details:

```json
{
  "code": "credits_exhausted",
  "scope": "account",
  "balance_credits": -5,
  "required_action": "top_up",
  "request_id": "..."
}
```

Other codes include `luna_daily_limit`, `luna_monthly_limit`, `hosting_payment_due`,
`sku_unpriced`, and `billing_temporarily_unavailable`.

The hosted UI renders the block directly. It must not rely on another paid LLM call to
explain why LLM spending is blocked.

## Admin Pricing section

Add a collapsible `Pricing` section to the management left pane:

- **Overview** — active/default version, customer liability, debt, current period
  credits/cost/margin, failed billing work.
- **Versions** — clone, edit draft, validate, publish, promote, rollout status, and
  immutable diff/history.
- **LLM & services** — commercial fixed context constants, global provider-cost versions,
  service SKU formulas, hosting, marketplace prices, and unpriced-service warnings.
- **Credit buckets** — recurring paid/bonus products, free recurring grants, signup/admin
  gifts, top-up steps, expiration, burn order, and Stripe bindings.
- **Simulator** — historical and hypothetical cost/margin simulation.
- **Accounts** — account balance/grants/ledger/debt, assigned version, subscription, safe
  gift/adjustment/reversal actions.
- **Stripe** — product binding status, subscriptions, payments, invoices, webhook/outbox
  failures.
- **Reconciliation** — provider totals, attributed costs, variances, unknown events,
  orphan resources, and rerun controls.

Every mutation requires admin auth, audit before/after state, actor, reason where
financial, CSRF-safe same-origin behavior, and server-side validation.

## Margin simulator

### Purpose

Use real past usage to answer:

- What did customers consume in credit face value?
- How much cash funded the consumed grant lots?
- What did vendors cost Luna?
- What fixed margin and gross profit resulted?
- What would happen under a draft commercial pricing version?
- What happens if an optimized Luna cuts LLM cost by 50%?
- Which context constant preserves or changes profit?

### Inputs

- period: default 28 days, arbitrary start/end, capped for interactive runs;
- all accounts or selected account/Luna/cohort;
- service, provider, model, context, and version filters;
- baseline and draft/published candidate commercial versions;
- provider-cost basis: original snapshot, latest reconciled cost, or a selected global
  cost version;
- vendor-cost transforms:
  - global LLM multiplier, e.g. `0.50`;
  - provider/model/context-specific multiplier;
  - explicit cost override;
- volume transforms for calls/jobs/resources;
- optional target fixed constants;
- replay mode:
  - `full demand`: rerate the same events even if a simulated wallet would block;
  - `wallet constrained`: replay grants, expirations, limits, and events in time order and
    mark events that would have been blocked.

### Calculation

For each logical billable operation:

1. Group all provider attempts by logical-call ID and preserve native quantities/context.
2. Apply the chosen provider-cost basis and scenario transform to each billable attempt.
3. Sum attempt costs and resolve the candidate commercial rule.
4. Add the fixed context margin once, then apply one final integer ceiling.
5. Aggregate the logical charge under the original root action/Luna/service.
6. In wallet-constrained mode, replay grant burn, expirations, holds, limits, and debt.

Never rewrite `billable_events`, `rated_charges`, ledger rows, or account assignments.
Simulation results store both config hashes and all scenario transforms.

Pre-039 `usage_events` lack trusted context, model, native cost dimensions, and logical
operation grouping. They may appear only as clearly marked estimated coverage and must
never be presented as exact rerating.

### Outputs

Top-level current versus candidate:

- calls/actions/resources;
- credits charged and $0.01 face value;
- cash basis allocated from consumed grants;
- vendor cost;
- fixed-margin amount;
- rounding;
- face-value gross profit/margin;
- cash-basis gross profit/margin;
- bonus/free/gift subsidy;
- Stripe fees/tax shown separately when available;
- accounts/Lunas that would reach zero, debt, or a limit;
- estimated blocked demand.

Break down by Luna, service, provider, model, context, commercial/provider-cost version,
grant source, and day. Show deltas and the largest winners/losers. Allow CSV export and
save reports.

`credits × $0.01` is not labeled cash revenue: subscription bonuses and free/gift credits
mean those figures differ. The simulator must show both or it will overstate margin.

### Optimized-Luna example

An admin selects a representative Luna, 28 days of events, candidate commercial version
2, and `LLM vendor-cost multiplier = 0.50`. The report rerates the same call mix at half
vendor cost, then lets the admin change `chat` or other fixed constants and recalculate
before publishing. This is a simulation only; it cannot alter production pricing.

## API surface

### Customer

- `GET /api/billing/balance`
- `GET /api/billing/grants`
- `GET /api/billing/usage`
- `GET /api/billing/usage/{root_action_id}`
- `GET /api/billing/products`
- `GET /api/public/pricing` for the marketing pricing page's active new-account catalog;
- `POST /api/billing/checkout/subscription`
- `POST /api/billing/checkout/topup`
- `POST /api/billing/portal`
- `GET /api/billing/invoices`
- `GET|PUT /api/agents/{id}/credit-limits`

All customer queries derive account from the authenticated membership. Only owners may
mutate plans, payment settings, auto-top-up, or limits.

### Admin

- version list/detail/clone/update-draft/validate/publish/promote/diff;
- simulation start/status/result/export;
- account balance/grants/ledger/assignment;
- gift/adjustment/reversal with reason;
- Stripe bindings/webhooks/retry;
- reconciliation run/items/resolve;
- invariant/replay checks.

Long simulation, rollup, and reconciliation work returns a job ID and runs through the
durable worker.

## Implementation phases

Each phase is a separate reviewable branch/PR and follows `skills/devprocess/SKILL.md`:
branch, scenario tests first, implementation, browser walkthrough, and execution report.

Detailed execution plans live in numbered phase folders inside this plan:

| Folder | Parent phase | Content |
|---|---|---|
| `001-migrations-and-ledger/` | A | migration tooling, schema, ledger, authorize/settle |
| `002-pricing-versions-and-admin/` | B | version workflow, assignments, admin Pricing UI |
| `003-luna-core-metering/` | Luna core | context/transport/events/blocks (Luna repo) |
| `004-gateway-metering-and-enforcement/` | C | billing-grade gateway, context resolution |
| `005-grants-hosting-and-limits/` | D | trial gifts, expiry, limits, hosting, services |
| `006-stripe-account-setup/` | E (prereq) | interactive: account, products, tax, webhooks |
| `007-stripe-integration/` | E | checkout, webhooks, grants, plan changes |
| `008-customer-billing-ui/` | F | credits page, usage dashboard, blocks, dojo |
| `009-simulator-and-operations/` | G | simulator, reconciliation, invariants, alerts |
| `010-rollout-and-migration/` | Rollout | observe→shadow→enforce, live Stripe, migration |

003 runs in parallel with 001–002. 006 is an interactive browser session (Stripe account
creation and dashboard configuration), not a code branch.

### Phase A — Migrations, immutable pricing, and credit ledger

Build:

- introduce migration tooling and production migration command;
- add pricing, billing account, grant, ledger, posting, consumption, hold, limit, outbox,
  and audit schema;
- implement integer rating helpers and validated version config;
- seed version 1 with the defaults in this plan;
- implement balanced transaction, grant, expiration, charge, reversal, and projection
  replay;
- implement atomic authorize/settle/release;
- add owner/admin authorization helpers;
- add `CLOUD_BILLING_MODE=off|observe|shadow|enforce`.

Tests first:

- postings balance and posted rows cannot mutate;
- credit value and published version are immutable;
- duplicate source/idempotency returns the original result;
- concurrent grants/charges/holds preserve a replayable balance;
- `5 → charge 10 → -5` posts fully;
- once nonpositive, a second action is blocked;
- one bounded overrun may start but concurrent uncovered overrun is blocked;
- burn order and each expiration policy are exact;
- reversal restores the correct economic source without editing history;
- projection equals full ledger replay.

Exit:

- admin/test code can create grants, authorize, settle, expire, reverse, and replay;
- no production cost path is debited yet.

### Phase B — Pricing admin and version assignments

Build:

- draft clone/editor/validator/publisher;
- immutable diff and audit history;
- account assignment and future rollout engine;
- product/provider/service coverage validation;
- Pricing navigation and pages for commercial versions, provider-cost versions,
  LLM/services, and buckets;
- environment-specific Stripe binding placeholders.

Tests first:

- edits create/modify a draft, never a published version;
- calls in flight keep both versions selected at authorization;
- `new_accounts` leaves existing accounts pinned;
- `all_accounts` changes only future charges after effective time;
- a provider-cost publication applies globally and cannot be cohort-pinned;
- rollback creates assignment history;
- enabled unpriced SKU cannot publish.

Exit:

- a version can move draft → validated → published → canary/new/all assignment with an
  audit trail, without yet collecting Stripe money.

### Phase C — Gateway metering and hard enforcement

Build:

- billing-grade provider adapters and attempt correlation;
- context resolution: forge job token, advisory agent/direct header, `agent` fallback,
  model-tier lookup;
- hold before upstream; event/rate/settle after usage;
- provider-specific native usage and cost;
- legacy `usage_events` dual-write for transition;
- stable block/error contract;
- Luna image compatibility from `luna-core-plan.md`;
- provider usage reconciliation and unresolved-operation worker.

Tests first:

- all provider fixture dimensions, SSE chunk splits, missing/duplicate usage;
- duplicate provider/request IDs do not double-charge;
- spoofed account/Luna headers cannot change attribution; spoofed model or forge claims
  cannot change the verified tier/context; a claimed `direct` is the only
  tenant-influenced discount and is bounded by the constant spread;
- timeout, disconnect, cancellation, fallback, and restart produce one explainable state;
- fallback attempts add at most one margin per successful logical call;
- no prompt/output enters billing data;
- concurrent calls respect balance, exposure, and Luna limits;
- unknown model/context/service fails closed only in enforcement mode.

Exit:

- every platform-keyed gateway request is `blocked`, `released`, `settled`, or
  `needs_reconciliation`;
- observe/shadow totals reconcile to provider reports before enforcement.

### Phase D — Grants, hosting periods, services, and resources

Build:

- trial signup gift issuance;
- expiry/hold reaper;
- per-Luna daily/monthly limits;
- hosting create/period/renewal/stop/recovery;
- runtime allocation hooks at the `LunaRuntime` interface;
- service/job/storage callbacks and interval accrual;
- platform-owned marketplace exact-price purchase/entitlement;
- usage rollups.

Tests first:

- grant/expiry/renewal jobs are safe to rerun;
- hosting charges exactly once per confirmed period;
- failed provisioning releases or reconciles;
- debt during a paid period blocks paid work but does not double-charge hosting;
- failed renewal stops and cannot restart without debt + 999 credits;
- duplicate/out-of-order resource events cannot double-accrue;
- one Luna limit can block without affecting another.

Exit:

- every launch cost surface is explicitly metered, included, or disabled;
- account and per-Luna statements cover hosting, LLM, services, jobs, storage, and
  marketplace.

### Phase E — Stripe subscriptions and top-ups

Build:

- Stripe SDK/config and `.env.example` documentation;
- Customer, Checkout, Portal, subscription, top-up, Tax, invoice/payment projections;
- verified durable webhook handling;
- paid + bonus grant issuance;
- upgrade/downgrade/cancel and auto-top-up;
- refunds/disputes/chargebacks.

Tests first:

- duplicate/out-of-order webhooks grant once;
- browser return grants nothing;
- failed/pending/later-successful payments behave correctly;
- top-up step cannot be altered client-side;
- refund of spent credits creates debt;
- upgrade grants once and resets anchor; downgrade waits for renewal;
- auto-top-up races create one payment and respect monthly cash cap;
- Stripe test clocks cover cycle renewal and failure recovery.

Exit:

- real Stripe test-mode money-in maps exactly once to visible grant lots and receipts.

### Phase F — Customer credits and usage dashboard

Build:

- credits/balance/product/top-up/subscription page;
- 28-day/custom usage dashboard and action details;
- AgentDetail spend card and limit editor;
- negative/blocked/expiry/payment notices;
- invoice/portal links and CSV statement;
- role-safe owner controls;
- UI handling of stable gateway block codes.

Dojo:

- trial signup shows the gift balance and its expiry; an exhausted or expired trial
  blocks paid work and subscribing to Hobby restores it;
- subscription shows paid + bonus separately and spends bonus first;
- multi-call chat groups child charges under one action;
- Luna A reaches its cap while Luna B can continue;
- 5-credit balance completes a 10-credit action, shows -5 in red, and blocks the next;
- top-up clears debt and restores paid work;
- paid hosting remains through period end, then stops on failed renewal;
- non-owner cannot mutate limits or payment;
- no customer page reveals internal dollars or margin.

Exit:

- a customer can understand every balance change and recover from a block without admin
  intervention.

### Phase G — Margin simulator and operations

Build:

- simulation job/replay engine;
- cost and volume transforms, including half-cost optimized-Luna scenario;
- current/candidate comparison and saved reports;
- face-value versus cash-basis margin;
- reconciliation, ledger invariant, orphan resource, failed webhook/outbox dashboards;
- alerts and exports.

Tests first:

- rerating never mutates production records;
- same config hash + same input snapshot produces the same result;
- half-cost transform changes vendor cost but preserves event count/context;
- changed fixed constant recalculates integer credits with exact ceiling;
- full-demand and wallet-constrained modes differ in labeled, expected ways;
- bonus/free grants reduce cash-basis revenue without changing credit face value;
- simulation aggregate equals a hand-calculated fixture.

Exit:

- admin can use real past X-day usage, model an optimized Luna, change constants in a
  draft, compare cost/margin, save evidence, and then separately publish/promote.

## Reconciliation and operations

Admin health signals:

- posted balance versus ledger replay;
- total active grant remainder versus category projections;
- credits granted, consumed, expired, reversed, and in debt;
- provider cost versus attributed events;
- credits charged, face value, cash basis, vendor cost, and gross profit;
- unreconciled provider requests and stale holds;
- failed Stripe webhook/outbox work;
- orphan Fly Machines/Volumes and failed stops;
- pricing coverage gaps and accounts without assignments.

Alerts:

- nonzero journal trial balance;
- projection/replay drift;
- paid provider call with no event after timeout;
- provider variance above configured threshold;
- unexpected negative-margin SKU/context;
- unbounded/stale open exposure;
- negative account balance;
- hosting period without matching runtime state;
- webhook/outbox retry exhaustion.

Run daily backups and complete a restore drill before enforce mode. Corrections are
append-only and require a reason.

## Rollout

The detailed sequence lives in `010-rollout-and-migration/PLAN.md`. Two ordering rules
are binding: live Stripe payment recovery exists **before** any customer-facing
enforcement (a blocked customer must have a real top-up path), and the block-aware
compatible Luna image ships **before** any account is enforced. Enforcement of internal
canaries uses a per-account/cohort enforcement override (gateway resolves the maximum of
the global `CLOUD_BILLING_MODE` and the account override) — `selected_accounts` is a
pricing audience, not an enforcement control.

1. Tests, security review, backup/restore drill, load budget.
2. Production `observe`: meter/rate only; no customer debit or block.
3. Compatible Luna image to internal canaries; verify call-context coverage.
4. Reconcile at least one complete provider billing period.
5. `shadow`: isolated shadow ledger; compare balances and block decisions.
6. Stripe live mode for internal canaries; verify real payment/refund/recovery.
7. Enforce internal canary accounts via the enforcement override.
8. Live subscriptions/top-ups for new accounts (still shadowed).
9. Enforce new trial accounts with version 1.
10. Migrate existing accounts in bounded cohorts after a signed dry run.
11. Promote to all accounts only after dashboard, recovery, and reconciliation evidence.
12. Enable platform-owned paid marketplace items after marketplace-specific gates.
13. Third-party sellers stay hard-disabled pending legal/Stripe Connect approval.

Operational modes and future assignments are reversible; collected money, posted
grants, and customer-visible blocks are not undone by configuration. Financial history
is never deleted or rewritten — corrections are append-only.

## Security requirements

- No raw provider key in an enforced hosted Luna.
- Hash tenant gateway tokens at rest and support immediate revocation.
- Verify all signed run envelopes and service callbacks with expiry + nonce.
- Verify Stripe webhook signatures against raw body.
- Derive account/Luna from authenticated server-side identity.
- Owner-only billing mutation; admin-only pricing/ledger mutation.
- Rate-limit Checkout, simulation, export, and grant endpoints.
- Never store prompts, outputs, tool arguments, API keys, card details, or unnecessary
  personal data in billing records.
- Encrypt sensitive provider/Stripe references where appropriate.
- Run a security review before live payments or enforce mode.

## Required verification

- Ledger property tests and real Postgres concurrency tests.
- Migration tests against a production-shaped backup.
- Provider contract fixtures for every enabled model/service response.
- Failure injection at each external-call/DB-commit boundary.
- Stripe CLI and test-clock webhook tests.
- Reconciliation against real sandbox/provider usage.
- Browser dojo for signup grant → subscribe → spend → limits → debt → top-up → recovery.
- Live agent walkthrough for chat, tool loop, playbook, background/summarization, and
  blocked-credit behavior.
- Load tests for authorization latency, statement queries, rollups, and simulator jobs.
- Security review of gateway identity, signed context, payments, and admin mutations.

## Definition of done

- Every platform-funded launch surface is metered, included, or blocked as unpriced.
- Every account has one explicit immutable pricing assignment.
- Every charge points to a raw event, root action, Luna, SKU, and pricing snapshot.
- Every balance movement is replayable, balanced, idempotent, and append-only.
- Concurrent requests cannot create unbounded debt.
- Negative balance behavior exactly matches the product vision.
- Recurring paid, bonus, top-up, free, and gift balances are visibly separate and burn in
  the configured order.
- Hosting charges once per paid Luna period and stops correctly after failed renewal.
- Stripe payment/webhook retries cannot duplicate grants.
- Customer usage is fully explainable in credits without revealing internal dollars.
- Admin can simulate a draft over past usage and hypothetical optimized Lunas without
  mutating production.
- Provider totals, customer charges, and cash economics are reconcilable.
- The compatible Luna core contract is shipped before context-specific enforcement.
