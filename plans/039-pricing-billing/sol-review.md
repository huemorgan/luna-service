# Sol implementation-objection review — phases 001–010 and Luna core

Recovered from the completed 2026-07-13 audit; no new review was performed while creating this file.

## Phases 001–005

Overall verdict: none of 001–005 is implementation-ready. The architecture is viable, but these plans still leave financial behavior to implementation-time improvisation.

## 001 — Migrations and ledger

Verdict: Block until migration cutover, chart of accounts, and debt allocation are specified.

High objections:
- Alembic already exists but has no revisions, uses a localhost URL, and production still performs startup DDL.

```51:58:cloud/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    from sqlalchemy import text
    from cloud.db.session import _get_engine
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for col, coltype in [
```

- “Define the chart of accounts before writing schema” is not a deliverable; the plan must define it.
- `debt_repayment` can double-move the wallet unless distinguished from grant allocation.
- “Current provider tariffs” is not a reproducible v1 seed. Existing `GatewayModel.input_cost/output_cost` are mutable floats and cannot fund billing.
- Balanced-posting enforcement needs an atomic posting protocol or deferred trigger; a normal row trigger rejects temporarily unbalanced multi-row inserts.
- Financial FKs must prevent account/agent hard deletion.

Phase/dependency concerns:
- Split the phase internally into baseline/cutover migration, billing schema, then ledger service.
- 002 must not start until canonical version hashing, model keys, and v1 provider-rate provenance are fixed.

Missing acceptance tests:
- Fresh empty DB and production-shaped pre-Alembic DB reach identical schema.
- Application startup has no DDL privileges.
- Same idempotency key with different payload is rejected.
- Commit/crash between transaction header and postings cannot expose partial money.
- Grant into debt allocates credits to prior uncovered charges without double-changing balance.
- Account/agent deletion cannot erase ledger history.
- Published→retired transition preserves immutable financial fields.

Exact corrective wording:
> Treat production as a pre-Alembic database. Add a hand-verified baseline for the complete existing schema. Fresh databases run baseline through head; existing production is stamped only after a schema-fingerprint check. Subsequent revisions add billing. Deploy runs migrations before application startup, after which all control-plane startup DDL is removed.

> The credit journal accounts are `customer_wallet`, `grant_issuance:{source}`, `credits_consumed`, `uncovered_debt`, `credits_expired`, and `manual_adjustment`. Luna-absorbed provider cost and GAAP revenue are not credit-ledger accounts.

> A charge posts `-credits` to `customer_wallet`, with the grant-backed amount credited to `credits_consumed` and the uncovered amount credited to `uncovered_debt`. A later grant posts once to the wallet; debt repayment reallocates the new grant to prior uncovered consumptions and transfers `uncovered_debt → credits_consumed` without a second wallet movement.

> Every financial mutation stores an operation ID and canonical request hash. Same ID and same hash returns the original result; same ID with a different hash fails.

## 002 — Pricing versions and admin

Verdict: Block. Publication currently has a circular Stripe dependency and two competing model-price sources.

High objections:
- Paid products require Stripe bindings before publication, but Stripe setup is phase 006. That prevents publishing v1 in 001/002.
- `gateway_models` already exposes mutable tier and float cost fields. The plan does not say that billing must ignore them.
- Assignment history lacks a no-overlap/no-gap rule and an explicit effective-dated new-account default.
- Enabling a global gateway model after publication can leave active commercial versions without a tier/rule.
- `all_accounts` rollout omits the durable future Stripe-renewal migration intent required by the umbrella plan.
- “CSRF-safe” is underspecified; current cookie-authenticated mutation routes have no explicit CSRF mechanism.

Phase/dependency concerns:
- Stripe binding should gate environment activation/checkout, not portable commercial publication.
- New-account assignment creation must be integrated atomically into `auth_routes.py`.
- 007 must consume rollout migration intents created here.

Missing acceptance tests:
- Account created during a rollout receives exactly one version at the DB effective timestamp.
- Assignment intervals cannot overlap or leave an authorized account unassigned.
- Rollout restart does not skip or duplicate accounts.
- Enabling a new model cannot make it billable under an unpriced active version.
- Editing `GatewayModel.input_cost`, `output_cost`, or `tier` cannot alter a charge.
- Cross-origin admin mutation is rejected.
- Canonically equivalent JSON produces the same hash.

Exact corrective wording:
> Commercial publication validates portable product keys and economics only. Stripe IDs live in environment-specific binding rows. Missing bindings block environment activation, checkout, and live promotion—not publication of the commercial version.

> `gateway_models` is routing/catalog metadata only. Its mutable `tier`, `input_cost`, and `output_cost` fields are never read by authorization, rating, reconciliation, or simulation. Commercial tier and provider cost come exclusively from snapshotted pricing versions.

> Commercial assignments are non-overlapping effective intervals per account. A separate effective-dated default determines new-account assignment. Account creation inserts the billing account and assignment in the same transaction.

> An `all_accounts` rollout stores both runtime assignment work and pending per-subscription renewal migration intent; completion requires both.

## 003 — Luna core metering

Verdict: Directionally correct, but not executable as written. Its `PLAN.md` is mostly a pointer, while the detailed proposal contains a correlation-model contradiction.

High objections:
- One `LLMCallContext.logical_call_id` scoped around `stream()` would incorrectly group every model node in a tool loop into one logical call.
- Pydantic `FallbackModel` requires one logical ID across fallbacks but a distinct attempt ID for each actual HTTP request. The wrapper placement is unspecified.
- Actual Luna has Anthropic, OpenAI, OpenRouter, Gemini, Ollama, Pydantic AI, and embedding paths. The plan lacks a supported/BYOK-only launch matrix.
- Root-action IDs have no defined source for chat turns, playbook runs, muted reactions, or post-turn condensation.
- Broad unpinned provider/Pydantic dependencies make the proposed explicit-client integration unstable.
- Policy blocks must be mapped before current fallback logic sees the 402.

Phase/dependency concerns:
- It can run parallel to 001/002, but the header contract must freeze before 004.
- `direct` pricing must remain disabled until a compatible Luna image is mandatory.
- The Luna repository needs an actual numbered execution plan, not only this dependency tracker.

Missing acceptance tests:
- Chat tool loop: one root action, distinct logical calls per model node.
- Pydantic and custom-router fallback attempts share logical ID but differ in attempt ID.
- Cancellation does not leak ContextVars into the next task.
- Background condensation inherits the chat root but gets a new logical call.
- 402 never triggers provider fallback under any fallback policy.
- Gemini/OpenRouter/Ollama behavior is explicitly hosted-metered or BYOK-only.
- Header transport preserves SDK authentication and strips content.

Exact corrective wording:
> `ExecutionScope` contains only root-action ID, call kind, caller, and optional envelope. `HookedModel` creates a new logical-call ID for each `Model.request()` or `request_stream()` invocation. Every actual provider HTTP attempt creates a new attempt ID. A fallback chain shares one logical-call ID across all attempts.

> The logical-operation wrapper sits outside fallback orchestration; provider transport instrumentation sits inside each attempted provider request.

> The plan must list each provider/path as `hosted-metered`, `BYOK-only`, or `unsupported`. No unlisted provider is considered covered.

## 004 — Gateway metering and enforcement

Verdict: Hard block. This is the highest-risk plan.

High objections:
- H3 remains explicitly unresolved.
- The current gateway forwards arbitrary methods and paths under a real platform key. Model checking alone does not prevent expensive unsupported endpoints such as batches, files, fine-tuning, or future provider APIs.
- New `X-Luna-*` headers would currently be forwarded upstream unless explicitly stripped.
- Worst-case estimation “from model limits” is unusable and does not actually bound debt unless output limits are enforced.
- Tenant-supplied logical IDs are untrusted; naïve uniqueness can become a charge-bypass.
- Tenant token verification currently resolves only an agent ID, without proving active account, hosting state, or billing identity.
- Forge job-scoped tokens do not exist in the schema.
- A stream-finalizer DB write can be cancelled or lost on process death.
- Requiring a complete provider billing period in this PR’s exit criteria is an operational rollout gate, not a code-phase exit.

Phase/dependency concerns:
- 004 should own the deny-by-default gateway route/SKU framework and LLM adapters.
- 005 should add non-LLM adapters through that framework, not duplicate gateway enforcement.
- Full-period reconciliation belongs in 010.

Missing acceptance tests:
- Every managed method/path is classified before upstream contact.
- Unknown endpoint never reaches upstream in enforce mode.
- Internal headers never reach providers.
- Same logical ID with altered account/body/model cannot dedupe a charge.
- Client disconnect after provider acceptance remains chargeable/reconcilable.
- Process death at every pre-send/post-send/event/settlement boundary.
- Mode matrix for off/observe/shadow/enforce, including billing DB failure.
- Alias and provider-returned model canonicalization.
- Revoked, deleted, blocked, and payment-due agents cannot spend.

Exact corrective wording:
> Managed gateway traffic is deny-by-default by `(service, method, normalized path)`. Each allowed route maps to one adapter and SKU. Unknown routes return `sku_unpriced` before upstream contact in enforce mode; observe/shadow record the would-block decision.

> A call is customer-chargeable once the gateway has initiated accepted provider work and receives a successful billable response or billable usage. Tenant cancellation, disconnect, timeout, or discarding the result never converts provider spend into Luna-absorbed cost. Absorption is limited to provider/platform failures that produced no usable provider result.

> Exposure uses the actual serialized input plus requested maximum output under the snapshotted tariff—not the model’s entire context window. When output maximum is absent, the gateway applies a configured ceiling. Authorization must enforce an output ceiling that keeps maximum uncovered liability within the configured cap.

> `off` bypasses billing; `observe` records events/ratings without wallet decisions; `shadow` executes decisions against an isolated shadow wallet without customer effects; `enforce` holds, blocks, and settles. Billing failure fails closed only in enforce mode.

> Internal correlation IDs are namespaced by authenticated agent and request fingerprint. Reuse with different immutable request facts is rejected, never deduplicated.

## 005 — Grants, hosting, limits, services

Verdict: Hard block. The current runtime lifecycle bypasses the proposed financial state machine.

High objections:
- Agent creation and retry use in-process `asyncio.create_task`; process death loses paid provisioning work.

```184:218:cloud/api/agent_routes.py
@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: CreateAgentRequest,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    # ...
    asyncio.create_task(provision_luna_for_account(str(account.id), agent_id=agent_id))
```

- Proxy traffic auto-wakes stopped/error machines, including a future payment-due machine unless explicitly blocked.
- Current start/stop/destroy routes perform Fly network calls while DB sessions are open.
- Agent deletion hard-deletes the row, conflicting with permanent Luna/action attribution.
- Trial active-Luna maximum is omitted; current API allows concurrent unlimited creation.
- Manual restart within an active paid period versus payment-due restart is not distinguished.
- Generic hold reaping can release holds after provider/resource spend.
- Basic Fly machine and 1GB volume may be charged twice: once by 999 hosting and again by resource accrual.
- Jobs, storage billing, and marketplace entitlement lack actual control-plane authorities. Marketplace packages are currently usable without an entitlement check.
- “Statements cover disabled services/jobs/storage/marketplace” is not a valid exit criterion.
- Monthly-anchor behavior for day 29–31 remains undefined.

Phase/dependency concerns:
- Add an explicit dependency on 002 because trial amount, active-Luna cap, and hosting price come from the assigned commercial version.
- Trial/account bootstrap must modify account creation atomically.
- Marketplace, job, and storage charging should remain disabled or become separate phases after their authority/enforcement points exist.
- Scheduled yearly-grant activation needs an owning worker phase.

Missing acceptance tests:
- Concurrent account callbacks issue one trial gift.
- Concurrent Luna creates on a trial account provision only one Luna and charge hosting once.
- Crash/retry at every provisioning state.
- Manual stop/start during an active period creates no second hosting charge.
- Payment-due Luna cannot auto-wake through proxy, scheduler, relay, or retry routes.
- January 31 anchor renews February last-day and returns to March 31.
- Early deletion preserves agent identity, hosting charge, and statement.
- Base machine/volume are not separately customer-charged.
- Stale hold with possible spend becomes `needs_reconciliation`, never released.
- Concurrent limit holds and full over-limit settlement behave correctly.
- Non-owner cannot change limits, gifts, hosting, or payment state.
- Marketplace item cannot be used without entitlement.

Exact corrective wording:
> New-account creation atomically creates the billing account, commercial assignment, and one trial grant. The assigned version supplies trial amount, expiry, and active-Luna maximum.

> Luna creation transactionally locks the billing account, enforces the active-Luna cap, creates a pending agent and hosting period, authorizes exactly 999 credits, and enqueues durable provisioning work. Provisioning occurs outside the transaction. Confirmed runtime resources settle the hold and activate the period; every partial state is idempotently recoverable.

> Every start, retry, provision, auto-wake, scheduler, and relay path passes through one hosting-state guard. Manual restart inside an active paid period is free. A `payment_due` Luna requires cleared debt and a newly paid hosting period and cannot be auto-woken.

> Agents are soft-deleted tombstones. Runtime and volume cleanup is durable outbox work; financial and usage attribution is never deleted.

> A stale hold may be released only when no external work started. Once dispatch/provisioning may have started, expiry transitions it to `needs_reconciliation`.

> The 999-credit basic hosting SKU includes the basic Luna machine and bundled base volume. Those resources are tracked as operator cost but are not separately customer-charged. Only explicitly defined excess storage or separate job resources receive additional SKUs.

> Jobs, paid storage, and marketplace remain disabled until each has a durable authority, idempotent source event, concrete price, and enforcement point. Disabled surfaces are reported as disabled—not claimed as statement coverage.

## Phases 006–010

Overall verdict: reject plans 006–010 as execution-ready. The architecture is viable, but these documents still leave payment correctness, recovery, replayability, migration, and marketplace behavior undefined.

Code reality supports that conclusion:

- Stripe is not installed or configured yet.
- `Account.plan` is only the legacy `"free"` label; membership roles exist but normal account auth does not expose/enforce owner role.

```40:62:cloud/db/models.py
class Account(Base):
    __tablename__ = "accounts"
    # ...
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="free")
# ...
class Membership(Base):
    # ...
    role: Mapped[str] = mapped_column(Text, nullable=False, default="owner")
```

- Current metering is explicitly best-effort telemetry, not billing-grade.

```252:270:cloud/db/models.py
class UsageEvent(Base):
    """One row per proxied request. billable=False for BYOK passthrough."""
    # ...
    input_tokens: Mapped[int | None] = mapped_column()
    output_tokens: Mapped[int | None] = mapped_column()
```

- Background work is in-process lifespan loops protected by advisory locks, not a durable leased outbox worker.

```141:162:cloud/main.py
# Background loops run in exactly one worker
# ...
forwarder_task = asyncio.create_task(
    run_exclusive(LOCK_RELAY_FORWARDER, "relay-forwarder", forwarder_loop)
)
# ...
reconciler_task = asyncio.create_task(
    run_exclusive(LOCK_RECONCILER, "reconciler", reconcile_loop)
)
```

- Public pricing still advertises Free/$29/$99 and “degrades gracefully,” contradicting trial/Hobby 19 and hard blocking.

```15:49:cloud/ui/src/marketing/pages/Pricing.tsx
const TIERS: Tier[] = [
  { name: 'Free', amount: '$0', /* ... */ },
  { name: 'Pro', amount: '$29', /* ... */ },
  { name: 'Power', amount: '$99', /* ... */ },
  // ...
];
// ...
'Free / Pro / Power / Enterprise...'
```

## 006 — Stripe account setup

Verdict: blocked.

Blockers/high objections:

1. Portal configuration contradicts the Stripe object topology. The plan creates one Product per product key but expects Portal-scheduled downgrades. Stripe only schedules period-end downgrades between Prices belonging to the same Product. More importantly, Portal-controlled upgrades cannot reliably implement Luna’s “full new bucket, reset anchor, grant once” policy. See [Stripe portal configuration](https://docs.stripe.com/customer-management/configure-portal).

2. Tax is not resolved by saying “SaaS/digital-services tax code.” Recurring prepaid credits, non-expiring top-ups, and later marketplace redemption may have different tax treatment. Stripe Tax also requires registrations and `automatic_tax=true`; merely enabling Tax and setting an origin does not collect tax. Tax must be excluded from granted-credit calculations.

3. The webhook is configured before 007 deploys the endpoint. That creates retries against a nonexistent route.

4. The restricted-key permissions are incomplete for auto-top-up/refund flows: PaymentMethods, SetupIntents where needed, Refunds, and PaymentIntents write access are not specified. Stripe recommends mapping actual API calls to permissions.

5. Event coverage is outdated/incomplete: prefer `refund.created|updated|failed`, add asynchronous Checkout events if any delayed method is enabled, and include dunning/finalization events. `charge.refunded` alone lacks a clean refund-level lifecycle.

6. Environment names conflict with the existing Pydantic prefix. Settings use `CLOUD_`, so the proposed `STRIPE_*` names would not load through `Settings`.

Phase/dependency concerns:

- 006 must consume the validated 002 draft catalog, insert environment bindings, and only then allow 002 to publish version 1. “002 finalized commercial version 1” plus “bindings required before publish” is circular.
- Webhook creation belongs after the 007 route is deployed to staging/test.
- Live tax registration and classification are rollout gates, not test-account setup prerequisites.

Missing acceptance tests:

- Restricted key successfully executes every expected SDK call and rejects unrelated APIs.
- Test and live objects/secrets cannot cross.
- Portal permits payment method, invoices, and cancellation but no unsupported plan switch.
- Tax-enabled Checkout collects/validates billing location and grants credits from pretax product consideration only.
- Webhook endpoint verifies raw-body signatures and rejects the wrong mode/secret.
- Every configured Price amount, currency, interval, lookup key, and local binding matches version 1.

Exact corrective wording:

> Stripe plan changes are code-owned. Checkout starts a new subscription only. Luna’s billing API performs upgrades and schedules downgrades; Billing Portal is limited to payment methods, invoices, tax IDs, and period-end cancellation. Portal plan switching is disabled.

> 006 consumes the validated but unpublished version-1 catalog from 002. After test bindings are entered and validated, 002 publishes version 1. The webhook endpoint is created only after 007 is deployed to the test environment.

> Use `CLOUD_STRIPE_SECRET_KEY`, `CLOUD_STRIPE_WEBHOOK_SECRET`, `CLOUD_STRIPE_PUBLISHABLE_KEY`, and an explicit `CLOUD_STRIPE_LIVEMODE=false|true`. Reject webhook events whose `livemode` does not match the environment.

> Before live mode, record the approved tax treatment and Product Tax Code separately for recurring buckets, top-ups, and marketplace purchases; configure required registrations; enable automatic tax in every Checkout/subscription flow; collect billing address and tax ID where applicable. Tax and Stripe fees never grant credits.

## 007 — Stripe integration

Verdict: reject; substantial payment-state specification is missing.

Blockers/high objections:

1. No durable worker implementation is assigned anywhere. `processed_webhooks` and `billing_outbox` tables are insufficient. Webhooks, scheduled grants, retries, dead letters, and auto-top-up require a worker with leases, heartbeats, retry backoff, and `FOR UPDATE SKIP LOCKED` claiming. Current lifespan tasks cannot guarantee completion after crashes/deploys.

2. Annual grant activation is undefined. Creating scheduled rows is only half the feature. The plan lacks:
   - the activation worker;
   - exact calendar-month boundary arithmetic;
   - ordering against expiration at the same instant;
   - late-worker recovery;
   - idempotency per lot;
   - testable clock abstraction.

   Stripe Test Clocks advance Stripe’s clock, not the application’s wall clock. Advancing an annual subscription will not automatically activate local monthly grants.

3. “Idempotency keyed on invoice ID” cannot identify multiple paid, bonus, and gift lots. Each annual invoice creates up to 25 distinct lots.

4. `invoice.paid` is not sufficient proof of collected money. Stripe can emit it for zero-value, customer-credit-funded, or manually marked-paid invoices. The handler must retrieve canonical Invoice/Subscription/InvoicePayment data and validate account, Price binding, currency, relevant pretax line amount, payment source, and active subscription state.

5. Subscription upgrade through Checkout risks creating a second subscription. Existing subscriptions must be updated using payment-dependent pending updates. Stripe’s default behavior can apply the upgrade despite failed payment.

6. Refund/dispute behavior is too vague for immutable grant lots:
   - partial refunds;
   - tax portions;
   - cumulative refunds;
   - annual scheduled lots;
   - refund failure;
   - dispute won/lost;
   - refund followed by dispute;
   - restoration after a won dispute.

7. Dunning remains undecided despite `review.md` M6. Under the parent invariants, granting grace credits without payment would introduce a new liability policy. Immediate credit blocking is the consistent launch decision, but it must be explicit.

8. Auto-top-up lacks SCA/off-session recovery. A saved method can require customer action. The system needs a stable failed state and customer CTA, not repeated PaymentIntent creation.

9. Marketplace refund coupling is absent. Refunding the funding grant can create debt after credits purchased a permanent entitlement. The entitlement policy must be explicit.

Phase/dependency concerns:

- Add a hard dependency on 002’s published catalog and durable-worker framework from 001.
- 005 does not currently specify a scheduled-grant activator despite 007 claiming dependency on “grant workers.”
- 007 must complete before 009; cash-basis simulation cannot merely be “enriched” by it.

Missing acceptance tests:

- Concurrent Customer creation produces one Stripe Customer.
- One annual invoice creates exactly 12 paid lots, 12 configured bonus lots, and one gift with distinct keys.
- Jan-29/30/31, leap-year, and final annual boundary behavior.
- Worker delayed past several boundaries activates every due lot once.
- Stripe Test Clock plus injected application clock activates the expected lots.
- Zero/out-of-band/wrong-currency/wrong-Price invoices grant nothing.
- Upgrade payment failure leaves the old subscription unchanged; later success applies once.
- Full and partial refund, refund failure, dispute won/lost, and refund-plus-dispute never double-claw back.
- Immediate failed-renewal block, Smart Retry/later payment, top-up while past due, and payment-method recovery.
- Auto-top-up SCA failure, monthly cap rollover, duplicate trigger, and threshold race.
- Webhook crash before/after event insert, outbox insert, Stripe retrieval, and ledger commit.
- No promotion code or discount changes paid-credit invariants unless explicitly supported.

Exact corrective wording:

> Checkout creates the first subscription only. An upgrade updates the existing subscription with `payment_behavior=pending_if_incomplete`, `proration_behavior=none`, and `billing_cycle_anchor=now`; the new full bucket is granted only from the resulting verified paid invoice. A downgrade is stored as a period-end pending change and applied idempotently at renewal. At most one active Luna Credits subscription may exist per account.

> Every grant uses a compound idempotency key: `stripe:{invoice_id}:{product_key}:{paid|bonus|gift}:{lot_index}`. A duplicate webhook returns the previously created lots.

> Annual lot boundaries are `period_start + i calendar months` using the original anchor day clamped to each month’s last day; lot 12 ends exactly at Stripe’s annual `period_end`. A durable worker activates every scheduled lot with `effective_at <= now`, under a row lock, exactly once. Tests inject `now`; Stripe Test Clock advancement is followed by running the activator at the clock’s frozen time.

> Launch dunning has no credit grace period. A failed renewal creates no grants and marks billing `past_due`; existing lots expire normally. Top-ups may restore a positive spendable balance while the subscription remains past due. A later verified payment grants once and clears the payment notice.

> Refund reversal is cumulative and proportional to the refunded pretax product amount: for each associated grant lot, the target reversed credits are `floor(original_credits × cumulative_refunded_product_amount / original_product_amount)`, capped at the original lot; a full refund reverses any rounding remainder. Scheduled credits are cancelled first, then active/unconsumed credits, then consumed credits, which may create debt. Tax and fees map to zero credits.

> A dispute uses the same payment-level clawback accumulator. `charge.dispute.created` applies the disputed target once; `won` restores it through new ledger postings; `lost` makes no second reversal. Refund and dispute handlers share one cumulative cap.

> A marketplace entitlement remains recorded after a funding-payment refund, but is unusable while account debt blocks hosted activity. A refund of the marketplace purchase itself atomically revokes the entitlement and restores credits under the marketplace reversal policy.

## 008 — Customer billing UI

Verdict: conditionally viable, but its “recover from any block” exit criterion is currently false.

Blockers/high objections:

1. Some blocks are not customer-recoverable: `sku_unpriced` and `billing_temporarily_unavailable` require operator/system action; `exposure_limit` may require waiting for holds rather than paying.

2. The plan does not assign ownership of the parent’s customer API surface. UI cannot rely on unspecified routes for balance, grants, products, usage detail, invoices, limits, Checkout, Portal, and CSV.

3. Recovery details are incomplete:
   - exact credits needed to clear debt;
   - additional 999 credits needed to restart a stopped Luna;
   - next Stripe retry and payment-action-required status;
   - scheduled downgrade/cancellation state;
   - annual future lots;
   - refund/dispute reversals;
   - stale hold/exposure recovery;
   - data-retention deadline.

4. Owner enforcement must occur server-side. Current `require_active_account` only returns `(User, Account)` after membership existence; it does not return/check `Membership.role`.

5. Marketing pricing is omitted even though the parent specifies `GET /api/public/pricing`. The current hardcoded page directly contradicts version 1.

6. Marketplace customer UX is absent. 005 promises exact-price purchase/entitlement, but 008 has no offer display, credit-price confirmation, insufficient-balance handling, purchase history, entitlement state, or reversal UI. Existing marketplace UI is admin image/plugin configuration, not customer purchasing.

7. Marketplace persistence is also missing upstream: neither the parent entity list nor 001 names marketplace offers, purchases, or entitlements.

Phase/dependency concerns:

- Explicitly depend on 003/004 for hosted block rendering and the compatible Luna image, not just 005/007.
- Dojo cannot pass “block without retry/LLM explanation” on the current Luna image.
- Marketplace UI must wait for explicit marketplace schema and APIs added to 001/005.

Missing acceptance tests:

- Owner versus non-owner API authorization, not merely hidden buttons.
- Debt recovery where top-up clears debt but remains below the 999 restart requirement.
- Failed renewal → payment method update → later paid invoice → grant/restart.
- `exposure_limit`, `sku_unpriced`, and temporary outage show distinct, truthful actions.
- Refund/dispute ledger rows and annual scheduled/cancelled lots are understandable.
- API, CSV, browser DOM, logs, and downloadable statements expose no internal USD, context, tier, or margin.
- Usage pagination, custom UTC boundaries, CSV totals, running balances, and concurrent postings.
- Dynamic public pricing equals the published new-account catalog.
- Marketplace insufficient balance, duplicate purchase, atomic entitlement, refund/revocation, and non-owner denial.
- Back/refresh/replayed browser return never grants or duplicates payment.
- Mobile/accessibility and screen-reader treatment of debt/blocked notices.

Exact corrective wording:

> The customer can recover without admin help from every customer-actionable block. Operator-actionable states such as `sku_unpriced` and `billing_temporarily_unavailable` show a retry/status path and never claim that payment will fix them.

> The recovery payload includes `debt_credits`, `credits_required_for_positive_balance`, `hosting_restart_credits`, `next_payment_retry_at`, `payment_action_required`, `open_exposure_credits`, and the exact recommended action. A stopped Luna shows the total required to clear debt and buy its next 999-credit period.

> 008 implements the full parent customer API surface and derives account and role server-side. Owner-only mutation uses a fresh membership-role check; non-owners receive 403 even when calling the endpoint directly.

> Replace the static marketing tiers with `GET /api/public/pricing`; version 1 displays the 28-day trial, Hobby 19, Recurring 100/200, yearly variants, and configured top-ups.

> Add customer marketplace offers, purchases, and entitlements. Every platform-owned item displays an immutable integer-credit price, requires confirmation, authorizes exact price, and atomically records purchase plus entitlement. Third-party items remain disabled and absent from purchase APIs.

## 009 — Simulator and operations

Verdict: blocked; reproducibility and operational ownership are not sufficiently specified.

Blockers/high objections:

1. “Same config hash + same input snapshot” is not implementable because the snapshot is undefined. A period/filter is not a snapshot. Reconciliation can change cost basis and late events can arrive.

2. Saved aggregate results are insufficient to reproduce or audit a financial simulation. The run needs a manifest covering event IDs/hashes, ledger sequence, provider-cost basis, code/algorithm version, ordering, and transforms.

3. `0.50` multipliers risk violating the no-float invariant. Scenario values need decimal-string or rational representation.

4. Wallet-constrained ordering is ambiguous for events sharing timestamps. Grant activation, expiration, authorization, settlement, and reversal ordering materially changes results.

5. Candidate grant behavior is undefined. A candidate commercial version can change recurring products, bonuses, expirations, and yearly gifts. The simulator must say whether it reuses actual historical grants or synthesizes candidate grants from actual payments.

6. Candidate holds must be recomputed. Replaying historical hold amounts under new pricing does not model whether the candidate would have blocked an operation.

7. 007 is a hard dependency for cash basis, invoice/refund state, and candidate product replay.

8. Operations omit:
   - Stripe cash/invoice/refund/dispute reconciliation;
   - scheduled annual lot activation backlog;
   - dunning and debt ageing;
   - marketplace purchase/entitlement reconciliation;
   - worker leases/dead letters;
   - alert delivery, deduplication, severity, owner, and runbook;
   - backup RPO/RTO and restore evidence.

9. “Negative account balance” as a raw alert will be noisy because bounded debt is expected. It needs age/amount/rate thresholds.

Phase/dependency concerns:

- Depend on 001, 002, 004, 005, and 007—not “enriched by 007.”
- The durable worker must exist before 007 and 009; assigning it only here is too late.
- Backup/restore, reconciliation, and alert gates must finish before any 010 enforcement.

Missing acceptance tests:

- Add a late event after a saved run; rerun by manifest remains identical.
- Reconciled cost changes do not alter an `original_snapshot` run.
- Rational half-cost transform has exact integer results with no floats.
- Deterministic same-timestamp ordering.
- Actual-grants versus candidate-products mode produces labeled differences.
- Candidate hold recomputation changes block decisions correctly.
- Cancellation/retry of long jobs does not publish partial results.
- Worker crash/lease expiry/reclaim/dead-letter behavior.
- Stripe invoice/payment/refund totals reconcile to local projections.
- Annual activation backlog and missed boundaries are detected and repairable.
- Marketplace purchase without entitlement and entitlement without charge are detected.
- Alert dedupe, acknowledgement, escalation, and recovery notifications.
- Full restore into an isolated database and invariant replay.
- Multi-tenant admin authorization and export rate/size limits.

Exact corrective wording:

> Every simulation stores an immutable run manifest containing: canonical filter JSON/hash; ordered billable-event IDs and row hashes; maximum ledger sequence; grant/payment/invoice IDs and hashes; baseline/candidate config hashes; provider-cost version IDs or reconciled-cost cutoff; scenario transforms as decimal strings/rationals; replay mode; ordering-policy version; simulator algorithm version; application git SHA; and result hash.

> Replay order is deterministic: `(effective_timestamp, event_priority, stable_source_id)`. Grant activation precedes authorization at the same instant; expiration is exclusive at `expires_at`; settlement/reversal follows its recorded ledger sequence.

> Simulation has two explicit funding modes: `actual_grants` replays historical grants and cash basis unchanged; `candidate_products` derives hypothetical grants from historical successful pretax payments using the candidate product mapping. Results label the mode prominently.

> Wallet-constrained mode recomputes candidate estimates and holds from operation start/end timestamps and candidate rules; it never reuses historical hold amounts as candidate truth.

> The durable billing worker uses leased jobs, heartbeats, bounded exponential retry, dead-letter state, idempotent handlers, and `FOR UPDATE SKIP LOCKED`. It processes webhooks, scheduled grants, expiry, renewals, rollups, reconciliation, and simulation jobs.

> Operations additionally reconcile Stripe cash/invoices/refunds/disputes, scheduled annual liabilities, debt/dunning ageing, and marketplace charge-to-entitlement integrity. Every alert defines threshold, severity, owner, delivery channel, dedupe window, acknowledgement, and runbook.

## 010 — Rollout and migration

Verdict: reject; the current ordering can strand customers and the migration still contains an explicit undecided placeholder.

Blockers/high objections:

1. Enforcement on new trial accounts precedes live Stripe. A blocked trial customer has no live recovery path.

2. Internal enforcement precedes deployment of the block-aware compatible Luna image. Old Luna code may retry/fallback or fail to render the actionable response.

3. `selected_accounts` is a pricing-assignment audience, not an enforcement control. `CLOUD_BILLING_MODE` is global, so the current design cannot enforce only internal accounts.

4. Existing-account migration amount and policy are literally undecided. It also omits:
   - active Luna hosting periods and anchors;
   - stopped/error Lunas;
   - account creation racing the migration;
   - dry run/resume;
   - aggregate liability checks;
   - legacy `Account.plan`;
   - idempotency and rollback-by-correction.

5. “Every switch is reversible” overstates reality. Enforcement and payments can be disabled, but collected money, posted grants, expirations, and customer-visible blocks cannot be undone by configuration.

6. Live-mode key flipping needs explicit mode isolation and webhook-secret handling. A deployment must reject test events in live mode and vice versa.

7. Storage retention after `payment_due` is undefined. Stopping is safe; deleting customer databases/volumes without a defined policy is not.

8. Marketplace enablement has no prerequisite for customer purchase UI, entitlement persistence, refund policy, or reconciliation.

9. A production-shaped migration test is not enough. Actual rollout needs a signed dry-run manifest with expected account/Luna/grant totals before mutation.

Corrected phase order:

1. Complete security review, backup/restore drill, load budget, all automated tests, and live walkthrough.
2. Deploy the compatible Luna image to internal canaries while billing remains `observe`.
3. Reconcile a complete provider billing period with explicit variance thresholds.
4. Run shadow ledger and compare balances/block decisions.
5. Configure Stripe live mode but expose Checkout only to internal canaries; verify real small payment, grant, refund, dispute simulation where available, failed payment, and recovery.
6. Enforce internal canary accounts using an explicit account/cohort enforcement override.
7. Open live subscription/top-up recovery to new accounts while they remain shadowed.
8. Enforce new trial accounts only after live recovery passes.
9. Dry-run and migrate existing accounts in bounded cohorts.
10. Promote enforcement to all accounts after reconciliation and support evidence.
11. Enable platform-owned marketplace purchases only after marketplace-specific gates.
12. Keep third-party sellers hard-disabled pending legal, tax, and Stripe Connect approval.

Exact migration decision:

> Define `cutover_at`. Accounts created at or after it receive the default new-account assignment and normal trial grant. Every pre-cutover account is migrated idempotently with source key `migration:{account_id}:v1`.

> Reconcile actual runtime state first. Let `N` be the number of confirmed running Lunas. Issue one 28-day `migration` gift of `999 × max(1, N) + 801` credits. Immediately charge 999 credits for each running Luna and create its first grandfathered hosting period beginning at migration time. This leaves 801 activity credits while preserving every running Luna for one paid period. Stopped/error Lunas receive no hosting period and require the normal 999-credit restart payment.

> The migration dry run records account count, running/stopped/error Luna counts, total grants, total immediate hosting charges, resulting liability, assignment counts, and a content hash. Execution must match those totals or stop. Reruns return prior results; corrections are append-only.

> Legacy `Account.plan` is no longer billing authority. Subscription and product state come from billing projections; existing UI must stop presenting `Account.plan` as the current paid plan.

Additional corrective wording:

> Add nullable per-account/cohort enforcement mode with audited effective timestamps. The gateway resolves `off < observe < shadow < enforce` from the global maximum and account override, allowing internal canaries without globally enforcing customers.

> “Operational modes and future assignments are reversible. Financial history is not deleted or rewritten; mistakes are corrected through append-only reversals or replacement assignments.”

> Plan 039 performs no automatic customer-data deletion for nonpayment. A failed hosting renewal stops compute but retains tenant database, R2 data, and Volume until a separately approved retention/deletion policy exists.

> Platform-owned marketplace rollout requires offer/purchase/entitlement schema, dynamic credit pricing, customer confirmation, exact-price atomic purchase, reversal/revocation policy, reconciliation dashboard, and browser dojo. Third-party offers are rejected server-side even if present in an external catalog.

## Detailed Luna core audit

Implementation-readiness review of the three Luna phases in `luna-core-plan.md`, cross-checked against `PLAN.md`, `003-luna-core-metering/PLAN.md`, `004-gateway-metering-and-enforcement/PLAN.md`, and read-only `luna/` + `cloud/gateway/` code.

---

## Luna core vs gateway-only

| Capability | Luna core required? | Evidence |
|---|---|---|
| Model tier verification | **Gateway only** | `cloud/api/gateway_proxy.py` `_requested_model()` + catalog gate (`_MODEL_GATED_PROVIDERS`) |
| Default `agent` when metadata missing | **Gateway only** | `PLAN.md` / `004` explicit; no Luna dependency for observe/enforce |
| Pre-upstream authorize/block (402, no provider call) | **Gateway only** | Not implemented yet; belongs in phase 004, not Luna |
| Billing-grade usage parsing / holds / settle | **Gateway only** | Today: regex `UsageScanner` in `cloud/gateway/metering.py` |
| Forward tenant metadata headers upstream | **Gateway only (pass-through)** | `_upstream_headers()` forwards non-hop headers except auth |
| Per-request `X-Luna-*` header injection | **Luna core** | Reasoning path bypasses `ModelRouter`; uses pydantic-ai strings |
| `logical_call_id` / `attempt_id` / `root_action_id` | **Luna core** (gateway can synthesize when absent, but not group multi-call chat) | Only `conversation_id` ContextVar exists today |
| `agent` / `direct` / `forge` classification | **Luna core** (forge token verification is gateway) | No `LLMCallContext` in tree |
| Lifecycle events (`llm.attempt.*`, `llm.completed`) | **Luna core** | Only `llm.called` (pre-call), `llm.utility_call`, `llm.fell_back` |
| Provider-native usage expansion | **Luna core** (local telemetry); **gateway** (financial) | `Usage` is 3 fields in `luna/luna/types.py`; providers collapse dimensions |
| Policy-block non-retry + structured UI | **Luna core** | No `ProviderPolicyBlockedError`; chat errors are generic strings |
| Signed execution envelope | **Deferred** (both sides) | Correctly deferred in plan |
| Forge job scope | **Split** — gateway verifies job token; Luna inherits scope | No Forge runner in Luna; `tokens.py` is agent `lsv1-` only |

**Bottom line:** Gateway can ship observe/enforce with “everything is `agent`” and gateway-parsed usage. **Direct pricing, multi-call correlation, and usable block UX require Luna core.**

---

## BLOCKER

### B1 — Phase 1 cannot exit on current pydantic-ai wiring

Plan assumes `HookedModel` + shared header transport on both stacks. Reasoning/chat/headless use **model strings**, not explicit provider objects:

```269:290:luna/luna/agent/runtime.py
def _build_reasoning_model(fallback_sink: list[Any] | None = None) -> Model | str:
    ...
    if len(strings) <= 1:
        return strings[0]
    ...
    return FallbackModel(strings[0], *strings[1:], fallback_on=_on)
```

Utility path goes through `ModelRouter` + custom `AsyncAnthropic`/`AsyncOpenAI` clients (`luna/luna/llm/providers/*.py`).

Hosted env *does* set proxy base URLs for pydantic-ai via `provision_env._emit_proxy_service()` (mirrors `LUNA_ANTHROPIC_BASE_URL` → `ANTHROPIC_BASE_URL`), but **per-request metering headers need httpx request hooks on explicit `AnthropicModel`/`OpenAIModel` providers** — not static client headers (pydantic-ai docs + issue #2035).

**Plan correction:** Add a phase-1 spike: build explicit models in `_build_reasoning_model()`, httpx `event_hooks` reading ContextVar at send time, prove with one streamed chat + one `utility_complete` call. Pin pydantic-ai version (`pyproject.toml` is `>=0.0.14` — too loose; client lifecycle is in flux per #3913).

---

### B2 — Gateway credit/policy blocks will trigger provider fallback on router path

Plan: policy blocks are non-retryable in **both** stacks. Router path today maps unknown 4xx (including future 402) to retryable `ProviderDownError`:

```159:164:luna/luna/llm/providers/anthropic.py
        except APIStatusError as e:
            if e.status_code == 404:
                raise ModelNotFoundError(...)
            raise ProviderDownError(str(e), provider=self.name, model=model, status_code=e.status_code) from e
```

`should_fallback()` treats `ProviderDownError` as retryable (`luna/luna/llm/router.py`). A 402 credits block could hit a second provider/key.

Pydantic-ai path is safer under default `availability` policy (402 falls through to “no fallback”), but still surfaces as generic HTTP error, not typed block.

**Plan correction:** Introduce `ProviderPolicyBlockedError(retryable=False)` in **phase 1** (before events/UI), parse gateway JSON in custom providers *and* pydantic-ai `ModelHTTPError` paths, short-circuit before `should_fallback` / `FallbackModel.fallback_on`.

---

### B3 — No `root_action_id`; billing grouping cannot work as specified

Plan requires `X-Luna-Root-Action-Id` and groups multi-call chat under one root action. Luna has `_current_conversation_id` only (`luna/luna/agent/runtime.py` ~82–84). No root-action minting at message/playbook/job boundaries.

Gateway can generate orphan logical/attempt IDs when headers are missing (`004` plan), but **cannot reconstruct “one user message → N model nodes → one root action”** without Luna.

**Plan correction:** Specify mint points: e.g. root action = user message UUID / playbook run ID / continue-turn ID; set ContextVar at `stream()` entry and playbook runner entry; child logical calls inherit it. Add to phase 1 (transport) not phase 2.

---

### B4 — Forge tagging in Luna phase 2 is premature

`PLAN.md`: “Forge (plan 034) is not operational yet.” No Forge runner or `forge` scope in Luna. Gateway has only agent-scoped `lsv1-` tokens (`cloud/gateway/tokens.py`).

**Plan correction:** Defer Luna `forge` scope + tests until Forge exists; gateway-only forge token type can land in 004 when Forge ships. Until then, seed SKU disabled (already in PLAN.md).

---

## HIGH

### H1 — Per-model-node logical calls not wired in `stream()`

Plan: each tool-loop model node = one logical call, one margin. `stream()` runs a single `agent.iter()` and only aggregates `result.usage()` once at end (~1655–1669). No per-node scope.

**Plan correction:** Phase 2 must explicitly open a new logical scope at each `Agent.is_model_request_node(node)` (or HookedModel must rotate `logical_call_id` per top-level `request()` — pick one; document it). Add integration test: chat → tool → second model = 2 logical IDs, 1 root action.

---

### H2 — `HookedModel` / `FallbackModel` attempt semantics underspecified

Plan: fallback attempts share `logical_call_id`, unique `attempt_id`. Research doc (`luna/research/aspect-oriented-hooks.md`) says wrap at `_build_reasoning_model`. Unclear whether wrapper goes **around** `FallbackModel` or around each chain member. Wrong placement could collapse attempts or double-count logical calls.

**Plan correction:** Mandate outer wrap of entire `FallbackModel`; emit `attempt_id` per inner `request`/`request_stream`; add test: primary 429 → fallback 200 = 1 logical, 2 attempts.

---

### H3 — Event migration will break Phase 018 assumptions

Today:
- `llm.called` fires **before** provider execution (`router.py` ~318–325) — misnamed for billing lifecycle.
- `llm.utility_call` is separate, best-effort (`utility.py` ~102–114).
- Phase 018 `plugin-cost` expects extended `llm.called` (`luna/plans/018-cost-rate-limiter/PLAN.md`).

Plan replaces with `llm.attempt.*` + `llm.completed` but alias rules are vague.

**Plan correction:** Document exact alias mapping for one release (`llm.called` → `llm.attempt.started` or deprecated shim). List Phase 018 plugin as migration consumer.

---

### H4 — Phase 3 UI/event contract doesn’t match current chat pipeline

- `AgentEvent` kinds: `delta | tool_call_started | tool_result | turn_done | notice | done` — no `policy_blocked` (`runtime.py` ~166–178).
- SSE errors become markdown `**Error:** …` and still call `onDone` (`luna/ui/src/lib/api.ts` ~1031–1035).
- `stream()` maps 4xx to generic friendly text (~1803–1807), not gateway JSON codes.

**Plan correction:** Add `AgentEvent(kind="policy_blocked", …)` + SSE event; UI handler distinct from `onNotice` (fallback) and generic `error`; wire `action_url` from host env (`LUNA_HOST_NAME` / dashboard base already provisioned).

---

### H5 — Caller inventory incomplete (phase 2 grep invariant will miss paths)

Confirmed LLM call sites **not listed** in plan:

| Site | Path | Expected kind |
|---|---|---|
| CLI one-shot | `luna/luna/cli.py` `router.complete` | `direct` (or out of scope for hosted) |
| Onboarding persona | `luna/luna/onboarding/service.py` `utility_complete` | `direct` |
| Memory forget verify | `plugin_memory/__init__.py` ~467 | `direct` |
| Post-turn condense task | `runtime.py` ~1699–1727 → `maybe_condense` → `utility_complete` | `direct` (nested root action) |
| Overflow retry | `runtime.py` ~1783 second `stream()` | same root action, new logical calls |
| Embeddings | `plugin_memory` `router.embed` | `direct`, no events today |

**Plan correction:** Expand invariant list + tests for each row.

---

### H6 — Gateway block contract mismatch with today’s proxy

Plan specifies 402 + `credits_exhausted` JSON. Current gateway policy denial returns **403** + `{"error":{"type":"forbidden","message":…}}` (`gateway_proxy.py` ~241–244). No billing authorize-before-upstream.

**Plan correction:** Align status codes and JSON schema between `PLAN.md`, Luna error parser, and gateway 004 **before** Luna phase 3 tests.

---

## MEDIUM

### M1 — Provider-native usage: Luna expansion is telemetry-only (OK), but embed path is empty

`OpenAIProvider.embed()` returns vectors only — no token counts (`openai.py` ~194–205). `ModelRouter.embed()` emits no events. Plan includes embeddings in phase 2.

**Plan correction:** Return embedding token counts where provider exposes them; emit `llm.attempt.completed` for embed logical calls.

---

### M2 — Advisory `direct` spoofing is accepted product risk

Plan/PLAN.md correctly bound leakage ($0.01 top-tier spread). Not a code blocker; reconciliation is the control.

---

### M3 — Streaming disconnect / partial spend

Gateway records usage in stream `finally` (`gateway_proxy.py` ~161–172) — OK for telemetry, not yet holds/reconciliation (004). Luna SSE cancel (`chat_event_stream` CancelledError) may abort client while upstream continues — gateway-side problem for 004, not Luna.

---

### M4 — Backward compatibility / BYOK

- BYOK passthrough when credential ≠ `lsv1-` (`gateway_proxy.py` ~290–305) — correct; headers ignored by upstream.
- `utility_complete` swallows event emit failures — fine for telemetry, but new lifecycle events should same-pattern or billing plugins may miss rows silently.
- `model_override` in tests uses string models — must still get HookedModel wrapper or phase 1 tests lie.

---

### M5 — Gemini / Ollama hosted bypass

`model_registry.py` comment: Gemini excluded (no base_url). Router still builds `GeminiProvider` without proxy. Utility path could use gemini if configured — unmeterable on hosted unless fail-closed in catalog.

**Plan correction:** Gateway 004 + provisioning: fail-closed for non-proxy providers in enforce mode (partially in PLAN.md security section; enforce in gateway, not Luna).

---

### M6 — `run_turn` lacks `caller`; `run_llm` lacks `call_kind` / `root_action_id`

Plan phase 2 adds these; signatures today don’t have them (`runtime.py` ~1049, ~1255). Playbook wiring assumed but `plugin_playbooks/runner.py` wasn’t readable from workspace (path sync issue) — verify during Luna implementation.

---

## Phase-by-phase readiness

| Phase | Ready? | Main gap |
|---|---|---|
| **1 — Context & transport** | **No** | pydantic-ai string → explicit provider + httpx hooks; root_action minting; policy error type before fallback |
| **2 — Classification & events** | **No** | Depends on 1; per-model-node scoping; incomplete caller list; Forge deferred; event alias spec |
| **3 — Policy block & UI** | **No** | Depends on 1–2; gateway JSON/status not defined; no UI banner type; router 402→fallback bug |

---

## Recommended plan corrections (priority order)

1. **Split Luna phase 1:** spike (explicit pydantic-ai models + httpx ContextVar hooks) → then shared lifecycle helper → then router provider hook parity.
2. **Move `ProviderPolicyBlockedError` + no-fallback guard to phase 1** — blocks wasted provider spend on router path.
3. **Define root-action mint table** (chat message id, playbook run id, job id) and set in phase 1 transport.
4. **Specify HookedModel placement** (wrap outer `FallbackModel`) and per-model-node logical-call policy in phase 2.
5. **Publish event alias table** for `llm.called` / `llm.utility_call` deprecation.
6. **Freeze gateway block JSON + HTTP status** in 004 before Luna phase 3 E2E tests.
7. **Defer Forge** in Luna plan until runner exists; keep gateway forge token design in 034/004.
8. **Expand caller invariant** (CLI, onboarding, memory forget verify, post-turn condense, embed, overflow retry).
9. **Pin pydantic-ai** to a tested minor after spike.

Gateway can proceed with 001/002/004 observe-enforce using missing metadata → `agent`, gateway-side usage parsing, and synthesized IDs. **Direct-tier pricing and trustworthy multi-call statements need Luna 1–2 before enabling context-specific constants** (rollout step 5 in plan — correct sequencing).
