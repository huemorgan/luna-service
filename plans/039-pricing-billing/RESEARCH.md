# 039 — Luna Credits research

**Research date:** 2026-07-13  
**Product definition:** `plans/039-pricing-billing/pricing_vision.md`

## Research question

Can Luna support one account-level credit system where:

- 100 credits always equal $1.00 of customer value;
- customers buy and spend only integer credits;
- all Lunas share the account balance;
- each LLM call is priced as provider cost plus a fixed context-specific margin;
- recurring paid and bonus credits are separate visible balances;
- top-ups are sold at face value;
- each Luna costs 999 credits per month and can have daily/monthly limits;
- a completed action may push the balance negative, after which paid activity stops;
- hosting continues through its already-paid month and then stops until debt is cleared?

**Finding: yes.** The existing control-plane and gateway already contain the main tenant
identity and call interception points. The current metering is telemetry, not yet accurate
enough to debit credits, and the gateway cannot currently distinguish chat calls from
playbook or other LLM calls.

## Fixed product assumptions

These are inputs from the pricing vision, not open research questions:

- Customer currency is **Luna credits**.
- **1 credit = $0.01; 100 credits = $1.00.**
- Customer charges are whole integer credits.
- Credits belong to `Account`, not `User` or `Agent`.
- Bonus, paid recurring, top-up, and free/promotional credits remain separate balances.
- Bonus credits are consumed first.
- Paid recurring credits expire at the monthly cycle boundary.
- Bonus expiration is independently configurable.
- Top-ups have no bonus.
- LLM margin is a fixed amount per call context, never a percentage.
- Each Luna costs 999 credits for a prepaid monthly hosting period.
- The account can become negative after a completed transaction.
- At zero or below, new LLM calls, services, and paid actions are blocked account-wide.
- A paid Luna server remains allocated until its hosting period ends, then stops.
- A stopped Luna cannot restart until debt is cleared and the next hosting period is paid.
- Each Luna can have independent daily and monthly credit limits.
- Free credits do not change the price of any action.

## Credit math

### Customer charge

For an LLM call:

```text
integer_credits =
    ceil((actual_provider_cost_usd + margin_constant_usd) / $0.01)
```

Equivalent:

```text
integer_credits =
    ceil((actual_provider_cost_usd + margin_constant_usd) × 100)
```

Example:

```text
Provider cost:          $0.037
Chat margin constant:   $0.020
Internal total:         $0.057
Customer debit:         6 credits
```

The customer sees `6 credits`; provider cost and margin stay internal.

### Why fixed margin works

A fixed per-call margin preserves alignment:

- If provider prices fall, the cost component falls.
- If caching or routing lowers provider cost, the cost component falls.
- Luna's fixed margin does not fall with it.
- Luna therefore benefits from maintaining the optimization while the customer also
  receives a lower price.

A percentage markup would make Luna's absolute margin shrink whenever provider cost is
optimized. That is not the desired business model.

### Credit granularity

Because charges are integer cents:

- Every positive calculated charge rounds upward to the next credit.
- Provider-cost reductions smaller than one cent might not change the displayed charge
  until they cross the next integer boundary.
- The rounding difference must be retained internally so realized margin remains
  explainable.
- Vendor cost should still be stored at finer precision, such as integer micro-USD; only
  the customer ledger and UI are integer credits.

Internal micro-USD is accounting precision, not a second customer currency.

## Context-specific LLM margins

The pricing vision requires different fixed constants for different call contexts:

- chat;
- playbook;
- summarization;
- background/autonomous work;
- Forge;
- future categories.

### Current finding

The credential gateway sees:

- agent identity;
- service/provider;
- request path and body;
- requested model;
- provider response and token usage.

It does **not** reliably know why Luna made the call. A chat call and a playbook call can
reach the same provider endpoint with the same model.

Therefore context cannot safely be inferred from provider, model, or URL. The originating
Luna runtime must attach a trusted call-context value or correlation ID that survives to
the gateway. Without that metadata, all LLM calls can only use one default margin.

The context must be constrained to an allowed catalog; a tenant must not be able to submit
an arbitrary cheaper category. The gateway-issued tenant identity is the existing trust
anchor, while the exact Luna-side contract will need a separate Luna proposal because the
`luna/` submodule is read-only here.

## Current account and tenant model

The existing schema already matches the desired ownership:

- `Account` owns many agents (`cloud/db/models.py`).
- `Membership` links users to accounts.
- `Agent.account_id` gives every Luna its billing account.
- Gateway tenant tokens resolve to `agent_id`.
- `agent_id → Agent.account_id` provides the account debit target.

No wallet, credit grant, Stripe customer, subscription, payment, expiration, debt, or
marketplace entitlement record exists yet.

The current `Account.plan` field is only a label. It does not grant credits or enforce
limits.

## Current gateway metering

`/proxy/{service_slug}/{path}` is the strongest existing seam because managed provider
credentials are inserted there before the external call.

Today it records `UsageEvent` with:

- agent;
- service;
- key;
- status;
- request count;
- input tokens;
- output tokens;
- billable flag.

Relevant files:

- `cloud/api/gateway_proxy.py`
- `cloud/gateway/metering.py`
- `cloud/db/models.py`
- `cloud/api/gateway_admin_routes.py`

### Why it is not billing-grade yet

`UsageScanner` searches response bytes with regular expressions. Missing information
includes:

- provider request/response ID;
- requested and canonical model on the usage row;
- call context such as chat or playbook;
- Anthropic cache creation/read token classes and cache duration;
- OpenAI cached, audio, image, and reasoning details;
- provider service tier and batch/priority differences;
- immutable price/margin version;
- durable idempotency key;
- an explicit account ID;
- accurate non-LLM operation units;
- each attempted fallback call.

The stream finalizer writes best-effort. A crash after the provider charged Luna can lose
the event.

OpenAI reasoning tokens are included in output usage, and Anthropic thinking is included
in output tokens. Detailed usage must be retained without charging those units twice.

No prompts, responses, file names, credentials, or conversation content are needed for
billing.

## Provider-cost calculation

The exact vendor cost of a call depends on more than input and output token totals.

### LLM dimensions that may affect cost

- Actual provider and canonical model.
- Normal input tokens.
- Cache writes/creation.
- Cache reads.
- Output tokens.
- Audio/image input and output.
- Server-side web search, containers, or other provider tools.
- Batch, priority, regional, or service tier.
- Provider price effective when the call occurred.

`GatewayModel.input_cost` and `output_cost` exist today, but they are mutable floats and
do not represent all these dimensions. They can inform initial prices but are insufficient
as historical cost evidence.

The customer debit needs to preserve:

```text
actual vendor cost
+ selected context margin constant
+ integer rounding
= credits charged
```

Both the provider price and margin constant require effective-dated versions so an old
charge never changes after an administrator updates pricing.

## Negative balances and bounded exposure

The product allows this:

```text
Balance before call:      5 credits
Final call charge:       10 credits
Balance after call:      -5 credits
```

This means the ledger cannot enforce a strict nonnegative-balance invariant.

The useful boundary is:

- A new paid action is rejected when the account is already zero, negative, or otherwise
  blocked.
- An action already allowed to start posts its full final charge.
- Concurrent in-flight actions can push the account further negative.
- Once the resulting balance is zero or negative, no new paid action starts.
- New grants/top-ups first clear debt; activity resumes only with a positive balance.

This creates intentional financial exposure. The unresolved research variable is how much
simultaneous in-flight exposure to permit per account. Per-account concurrency limits,
maximum call output, Forge/job caps, and provider rate limits can bound it without hiding
real costs or truncating completed charges.

The account UI needs:

- negative total shown in red;
- the debt amount;
- blocked status;
- which in-flight actions created the overrun;
- the amount required to resume.

## Separate customer-visible balances

The account has one total plus visible components:

```text
Total credits
├── Bonus credits
├── Paid recurring credits
├── Top-up credits
└── Free/promotional credits
```

Example recurring grants:

| Monthly payment | Paid credits | Bonus credits | Total |
|---|---:|---:|---:|
| $100 | 10,000 | 1,000 | 11,000 |
| $200 | 20,000 | 5,000 | 25,000 |

This separation is useful beyond presentation:

- Bonus and paid credits can expire differently.
- A refund can reverse only the appropriate paid grant.
- Promotional/free credits can carry distinct rules.
- Consumption order remains explainable.
- A user can see what expires and when.

The chosen order is bonus first, then other expiring promotional credits, then paid
recurring credits, then top-ups.

When all positive grant lots are exhausted, further completed charges create account debt
rather than a negative grant lot.

## Stripe fit

### Recurring buckets

Stripe subscriptions can collect the monthly payment. A verified successful invoice
event can identify the purchased bucket:

```text
$100 subscription payment
→ 10,000 paid recurring credits
→ 1,000 separate bonus credits
```

Both grants share the billing-cycle reference but remain separate balances with separate
expiration policies.

### Top-ups

Stripe Checkout or PaymentIntent can sell one-time credits at face value:

```text
$100 top-up → 10,000 top-up credits
```

Credits must be granted from verified, idempotent server-side payment events, never from
the browser return URL. Stripe can deliver duplicate and out-of-order webhooks.

### Why Stripe Billing Credits are not the Luna wallet

Stripe Billing Credits:

- apply to metered subscription items;
- are applied around invoice finalization rather than on every Luna action;
- do not model Luna's negative real-time balance and service lock;
- do not naturally represent the 999-credit Luna hosting purchase;
- do not apply to one-time invoice items;
- cannot be used for third-party payments.

Therefore Stripe is the payment collector and invoice/receipt system. Luna's control-plane
ledger remains the source for customer-visible balances and consumption.

Stripe's current documentation recommends Metronome for new complex usage billing, but an
external meter still does not know Luna's trusted call context automatically or replace
the immediate account-wide service lock.

## Luna hosting research

The desired commercial charge is simple:

```text
999 credits = one Luna's next monthly hosting period
```

The current Fly runtime already has the required identifiers:

- agent and account;
- Machine ID;
- Machine size and region;
- Volume ID and size;
- create/start/stop/destroy operations.

Current Fly configuration has `autostop: "off"` and `min_machines_running: 1`, so Lunas
are presently always-on. Charging a fixed monthly existence price is therefore clearer to
customers than exposing per-second infrastructure billing.

Fly itself charges:

- started Machine time;
- root filesystem while stopped/suspended;
- Volumes while they exist;
- Volume snapshots.

The customer price remains 999 credits regardless of the underlying provider invoice.
Vendor usage is still needed internally to verify whether 999 credits produces acceptable
margin.

### End-of-period behavior

If usage makes the account negative during an already-paid hosting period:

- the server allocation remains through that period;
- the Luna is inactive because paid calls/services are blocked;
- the server stops when the paid period ends;
- it cannot restart until debt is cleared and another 999 credits are available.

The remaining pricing questions are proration on creation/deletion and the exact monthly
anchor per Luna.

## Per-Luna limits

Gateway usage is already attributed to `agent_id`, so both account and per-Luna totals are
possible.

Required views:

- credits consumed today by Luna;
- credits consumed in the Luna's current monthly limit window;
- configured daily limit;
- configured monthly limit;
- account-level balance/block state.

Crossing a Luna limit blocks only that Luna. A zero/negative account balance blocks every
Luna.

The existing `monthly_request_cap` counts requests in a rolling 28-day window. It is not a
credit limit and does not match the pricing vision.

## Free credits

Free credits are grants, not cheaper prices.

The same call:

- measures the same provider cost;
- selects the same call-context margin;
- produces the same integer-credit debit.

Only the funding source differs. This prevents a separate free-tier rating system and
makes conversion to a paid bucket predictable.

Daily free grants and monthly free grants can coexist because each grant carries its own
effective and expiration interval.

## Non-LLM services

The gateway also proxies services such as search, Composio, and browser providers. For
these, provider cost might use:

- calls;
- search results;
- browser minutes;
- connected accounts/seats;
- generated media;
- bytes;
- monthly service allocation.

The same customer rule can still produce integer credits:

```text
ceil((vendor cost + fixed service/action margin) × 100)
```

Some platform-funded services currently receive real keys through legacy env provisioning
or `key_mode=env`, bypassing the gateway. Tavily is a known review point. A service cannot
be reliably credit-rated unless calls cross the gateway or its trusted service reports
idempotent usage.

Scheduler and WhatsApp are separate always-on services. Their shared fixed cost cannot be
measured exactly per Luna; per-agent or per-action credit prices can be fixed commercially
while vendor cost is reconciled internally.

Plugin Forge already anticipates a job-scoped gateway token and cost cap, which provides a
natural correlation point for all LLM and compute charges belonging to one job.

## Storage and shared infrastructure

### Dedicated resources

Fly Machines and Volumes can be attributed to one agent. The runtime lifecycle is visible
in `cloud/runtime/fly_machines.py`.

### R2

R2 uses per-agent prefixes and can report object bytes, while Cloudflare charges storage
plus Class A/B operations. The current helper only lists prefix size and R2 is not yet
wired as a full runtime storage path.

### Render and tenant Postgres

Render exposes service/database metrics but not an exact per-tenant invoice split. Shared
control-plane and Postgres cost therefore cannot be honestly described as pass-through
per Luna.

This does not conflict with credits. Customer pricing can use fixed credit charges while
the operator compares aggregate credits with aggregate shared vendor cost.

## Marketplace finding

Technically, Luna's own ledger can debit an integer one-time plugin price and create an
entitlement.

For platform-owned plugins this is a normal Luna sale.

For third-party plugins, payment from previously purchased Luna credits creates additional
merchant-of-record, tax, seller-payable, refund, chargeback, and possibly stored-value
questions. Stripe Billing Credits explicitly prohibit applying credits to third-party
payments.

The product vision can keep one credit price for marketplace items, but third-party seller
activation requires confirmation of the legal and Stripe Connect structure. Implementing
the arithmetic alone does not resolve that constraint.

## What current code proves

| Requirement | Current evidence | Gap |
|---|---|---|
| Shared account wallet | `Account` owns agents | No credit ledger |
| Per-Luna attribution | Gateway token resolves `agent_id` | Usage rows require account rollup |
| LLM interception | Managed calls cross gateway | Parser is telemetry-grade |
| Actual provider cost | Token counts + model catalog exist | Missing full usage classes and versions |
| Context margins | Luna knows originating action | Gateway does not receive trusted context |
| Negative balance lock | Gateway has a pre-call policy hook | Current policy counts requests, not credits |
| 999-credit hosting | Runtime owns Machine lifecycle | No hosting period/renewal record |
| Per-Luna limits | `agent_id` exists on usage | No credit daily/month windows |
| Recurring paid/bonus | Stripe can collect subscriptions | No Stripe or grant records |
| Top-ups | Stripe supports one-time payments | No idempotent credit grant flow |
| Separate balances | Different grant sources are representable | No customer wallet UI |
| Marketplace credit price | Plugin catalog/install path exists | No offers, purchases, entitlements, seller accounting |

## Main risks found

- The gateway cannot currently distinguish chat versus playbook LLM calls.
- Regex token extraction can misprice cache, reasoning, media, and provider-tool usage.
- A crash can lose a best-effort usage event after vendor spend.
- Concurrent in-flight calls can deepen the intentionally negative balance.
- Raw provider keys can bypass platform metering.
- Shared services cannot be attributed with false per-tenant precision.
- Changing provider prices or margin constants without versioning makes history
  unreproducible.
- Duplicate Stripe/provider events can grant or debit twice without durable idempotency.
- Third-party marketplace credit purchases require more than technical ledger support.

## Questions still open in the pricing vision

- Exact margin constant for each call context.
- Trusted context names and Luna-to-gateway propagation contract.
- Complete recurring bucket catalog.
- Bonus expiration policy.
- Top-up expiration policy.
- Free daily/monthly grant quantities.
- Maximum allowed concurrent/in-flight negative exposure.
- Per-Luna limit reset windows and timezone.
- Hosting proration for create/delete.
- Fixed credit formulas for non-LLM services.
- Third-party marketplace merchant-of-record and seller payout structure.

## Sources

Official sources checked on 2026-07-13:

- Stripe Billing Credits — limits and prohibited third-party use:
  https://docs.stripe.com/billing/subscriptions/usage-based/billing-credits
- Stripe usage billing and Metronome recommendation:
  https://docs.stripe.com/billing/subscriptions/usage-based/implementation-guide
- Stripe webhook ordering and duplicate handling:
  https://docs.stripe.com/webhooks
- Stripe Connect marketplace responsibilities:
  https://docs.stripe.com/connect/marketplace
- Stripe Tax for marketplaces and digital products:
  https://docs.stripe.com/tax/tax-for-marketplaces
  https://docs.stripe.com/tax/digital-products
- Anthropic prompt-cache usage fields:
  https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- OpenAI API schema:
  https://platform.openai.com/docs/static/api-definition.yaml
- Fly Machine, rootfs, Volume, and snapshot billing:
  https://fly.io/docs/about/billing/
- Cloudflare R2 metrics and retention:
  https://developers.cloudflare.com/r2/platform/metrics-analytics/
- Cloudflare R2 pricing:
  https://developers.cloudflare.com/r2/pricing/
- Render metrics API:
  https://api-docs.render.com/reference/metrics
- OpenMeter/Stripe responsibility split:
  https://openmeter.io/docs/integrations/stripe/overview
- Metronome prepaid credits:
  https://docs.metronome.com/guides/pricing-packaging/billing-model-guides/prepaid-credits
- Stripe's immutable ledger design:
  https://stripe.dev/blog/ledger-stripe-system-for-tracking-and-validating-money-movement
