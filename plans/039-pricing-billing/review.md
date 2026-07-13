# 039 Pricing & Billing — Plan Review

**Reviewed:** `pricing_vision.md`, `RESEARCH.md`, `PLAN.md`, `luna-core-plan.md`
**Review date:** 2026-07-13
**Verdict:** Sound architecture, ready to start Phase A after resolving the High findings below. The documents are internally consistent with each other; the issues are gaps and edge cases, not design flaws.

## Strengths

- Correct core financial design: double-entry ledger with DB-enforced zero-sum postings, integer micro-USD everywhere, append-only corrections, idempotency keys on every money movement.
- The commercial-version / provider-cost-version split is well reasoned (PLAN.md §Pricing, rationale at line 244) — retaining a customer on old margins without retaining Luna on old vendor costs.
- Trust boundary analysis is honest: the plan explicitly concedes that tenant code cannot be attested and treats context pricing as never the only cost-recovery control.
- Observe → shadow → enforce rollout with reconciliation gates before customer debits.
- Legacy `key_mode=env` / `LEGACY_REAL_KEY_VARS` bypass is identified and gated before enforcement.
- Code claims in RESEARCH.md check out (e.g. `Base.metadata.create_all` at `cloud/main.py:57`; all referenced files exist).

## High — resolve before Phase A/B

**H1. First free-recurring grant timing can make free signup unusable.**
Signup gift is 500 credits; Luna creation requires 999. PLAN says "a monthly worker creates the free recurring grant" (line 496) — if the first 1,099-credit grant arrives only on the worker's schedule, a new free account cannot create its one Luna. The plan must state that the first free recurring grant is issued synchronously at account creation (the "1,099 funds one hosting period + 100 activity" rationale at line 107 implies this, but it is nowhere specified).

**H2. `other` is not a safe default against the most expensive context.**
Missing/invalid envelopes rate as `other` ($0.020), but `forge` is $0.050. Forge code running inside the tenant that omits its envelope is charged *less*, not more — the fail-safe direction inverts for the priciest context. Either make the fallback constant ≥ the maximum context constant, or have the gateway bind forge job tokens to the forge context server-side (the job envelope is control-plane-issued, so the gateway can know a token belongs to a forge job without trusting headers).

**H3. "No usable result → Luna absorbs cost" needs a gateway-side definition.**
PLAN line 152 absorbs provider cost when a logical call "produces no usable result," with no definition of usable or who decides. If the tenant can influence it (cancel, disconnect, discard the response), this is a cost-shift attack: burn provider spend, pay nothing. Define "usable" strictly from the gateway's view (provider returned a completed billable response ⇒ customer is charged, regardless of what Luna did with it) and reserve absorption for provider-side failures only.

**H4. Hosting renewal vs per-Luna monthly limit is unspecified.**
Hosting counts toward the Luna's monthly limit (line 169). Two problems: (a) an owner-set monthly limit below 999 makes renewal exceed the limit — is renewal blocked (bricking the Luna) or exempt? (b) the limit window is a UTC calendar month while the hosting anchor is per-Luna, so two 999-credit renewals can land in one limit window (e.g. anchor on the 1st, UTC drift), instantly exhausting a free Luna's 1,099 monthly limit. Specify that hosting charges count toward the limit for display but are not blocked by it, or exempt hosting from the limit entirely.

**H5. Version 1 seed is incomplete for non-LLM services.**
Decisions-and-defaults covers LLM constants, hosting, and credit products only. Phase D meters services, jobs, storage, and marketplace, and unpriced SKUs fail closed in enforce mode — but no default credit prices exist for search/Composio/browser/storage/jobs/marketplace anywhere in the plan. Before Phase D, either publish concrete v1 prices for each launch service or explicitly list which SKUs launch disabled/included-free. RESEARCH.md flags this as open (line 533); PLAN never closes it.

## Medium

**M1. Block contract is missing a code for "positive balance, blocked by exposure."**
An action whose worst-case estimate exceeds spendable-plus-1,000-overrun is rejected while the balance is positive. None of the listed codes (`credits_exhausted`, limits, `hosting_payment_due`, `sku_unpriced`, `billing_temporarily_unavailable`) describes this; `credits_exhausted` with a positive `balance_credits` would be confusing. Add a code (e.g. `exposure_limit`).

**M2. Worst-case hold sizing will block legitimate low-balance usage.**
Estimating exposure "from model limits" (gateway flow step 4) can mean hundreds of credits per call for large-context models. A 500-credit account could be unable to start a 6-credit chat call. The plan needs an estimate policy (capped/percentile-based estimates, or model-output caps for low balances) — otherwise the required `5 → 10 → -5` behavior works in tests but real users get blocked far above zero.

**M3. Chat envelope minting depends on an unverified architecture assumption.**
`luna-core-plan.md` assumes "ingress middleware" can place a control-plane-signed envelope into the chat call context. If the hosted chat UI talks directly to the tenant Fly machine without traversing a control-plane component per turn, there is nowhere trusted to mint per-turn chat envelopes and all chat rates as `other` (same price in v1, so no revenue impact, but the machinery is dead weight until fixed). Verify the actual chat ingress path before Phase C.

**M4. Authorization latency and hot-row contention are unbudgeted.**
Every LLM call now performs a locked read-modify-write on the account row plus hold insert before first token, serializing an account's concurrent calls. Load tests are listed, but no latency budget or mitigation is named. Worth deciding up front whether authorize is per logical call (once per chat turn) rather than per attempt, and what the target added latency is.

**M5. Free tier funds a real always-on Fly machine with zero cash.**
75/day and 1,099/month limits bound LLM spend, but the machine itself is real vendor cost per free account, and nothing in scope addresses signup abuse (N free accounts = N free VMs). This may belong to a separate abuse plan, but 039 should state that dependency explicitly before enforcing on new free accounts (rollout step 8).

**M6. No dunning/grace period on failed renewal.**
Failed subscription renewal creates no grants and paid credits expire at the cycle boundary, so the account hard-blocks immediately. Stripe Smart Retries take days. Decide deliberately: immediate block (current plan) vs a short grace window; if immediate, notices in Phase F must be aggressive.

**M7. Rollout steps 8–9 ordering leaves blocked users without recovery.**
Enforcement on new free accounts (step 8) precedes live Stripe (step 9). A blocked free account has no top-up path until step 9. Either swap the order or accept and document that early free accounts can only wait for the next monthly grant.

**M8. The ledger chart of accounts is not enumerated.**
Postings sum to zero, but against which accounts (customer liability, revenue, debt, expiration, Luna-absorbed cost)? Phase A schema cannot be written without this. Small effort, but it must be designed, not improvised in a migration.

**M9. Existing-account migration grant is unspecified.**
Rollout step 10 mentions "opening gift/grant" for existing accounts with no size or policy. Needs a decision before step 10, ideally seeded as a product in version 1 so it is versioned like everything else.

## Low

- **L1.** Calendar-month anchor arithmetic for day-29–31 anchors is undefined (Jan 31 → Feb 28 → Mar 28 or Mar 31?). Pick a rule (e.g. anchor-day-or-last-day, Stripe's behavior) and state it.
- **L2.** "End of account month" (free grant expiry) is an undefined term — presumably UTC calendar month or account-creation anchor; say which.
- **L3.** Alembic introduction is a real prerequisite hiding inside Phase A — the repo currently creates schema via `create_all` on startup. Budget it as its own work item; migrating the existing schema to a baseline migration against production is non-trivial.
- **L4.** In v1, `chat` = `other` = $0.020, so the entire envelope machinery changes pricing only for `playbook`/`background`/`summarization` (cheaper) and `forge` (see H2). That is fine, but it means Phase C's envelope work can be validated with zero revenue risk — worth exploiting in the rollout.
- **L5.** `pricing_vision.md` still says free grants may be "daily or monthly" and lists TBDs that PLAN has since resolved. Update the vision or mark it superseded by PLAN §Decisions to avoid two sources of truth.

## Cross-document consistency

Checked vision → research → plan → luna-core: no contradictions found. All 20 non-negotiable rules trace to the vision's invariants. Of RESEARCH.md's eleven open questions, PLAN resolves nine; the two still open are non-LLM formulas (H5) and third-party marketplace payouts (correctly deferred out of scope). The luna-core proposal correctly keeps all financial authority in luna-service and its three-phase delivery aligns with PLAN Phase C's dependency.

## Resolution log (2026-07-13)

- **H1 resolved:** signup gift raised to 1,800 credits (configurable), covering the first
  999-credit hosting period regardless of free-recurring grant timing. PLAN updated.
- **H4 resolved:** per-Luna limits measure consumption only; hosting charges do not count
  toward daily or monthly limits. Hosting is a versioned credit price because future Luna
  server tiers may cost more than 999. PLAN updated.
- **H5 resolved (mechanism):** billable SKU catalog is a dynamic JSON list inside the
  version's `config_json`; v1 seeds non-LLM SKUs disabled until priced. PLAN updated.
  Concrete non-LLM prices still to be defined before enabling those SKUs.
- **H2 deferred:** Forge is not operational yet; its SKUs (machine-time per-minute
  constant + LLM at the `forge` context constant) are seeded disabled in v1, so the
  cheap-fallback inversion is moot at launch. Before enabling Forge SKUs, the gateway
  must rate calls made with a forge job token as `forge` regardless of headers.
- **H3 resolved (2026-07-13, via Sol review adoption):** gateway-side chargeability
  definition written into PLAN.md and 004 — a call is chargeable once the gateway
  initiated accepted provider work and receives a billable response/usage; tenant
  cancellation/disconnect/timeout/discard never converts provider spend into
  Luna-absorbed cost; absorption only for provider/platform failures with no usable
  provider result.
- **Classification redesign (owner decision):** chat/playbook/background/summarization/
  other replaced by `agent` / `direct` / `forge`, with `agent` and `direct` split by a
  gateway-verified model tier (top/mid). Forge is verified by its job token; unknown
  context rates as `agent` (most expensive), so stripping metadata never lowers a price.
  Signed envelopes deferred to optional hardening — worst-case tenant leakage is the
  agent→direct spread ($0.01/call top tier). This resolves H2 fully and dissolves M3
  (chat needs no envelope minting path). The classification is internal-only: never
  shown in customer metrics, statements, or to the agent; customer breakdowns use
  functional root-action types (chat, playbook run, scheduled run, forge job). PLAN and
  luna-core-plan updated throughout.
- **Product pivot (owner decision):** no perpetual free tier — a 28-day trial gift
  (1,800 credits) plus a Hobby tier at $19/month (1,900 paid credits, one basic Luna).
  Yearly variants added for all buckets: 12× monthly price with no dollar discount, extra
  credits granted to the gift bucket (default: one month's paid credits). PLAN and vision
  updated; free recurring grant and monthly free-grant worker removed. This also
  supersedes M5 (free always-on VM abuse) — free compute now lasts at most one trial
  month per account, though throwaway-account signup abuse remains worth a control.

- **Sol review (2026-07-13, `sol-review.md`) — adjudicated.** Adopted (plans updated):
  Alembic baseline/fingerprint cutover with startup DDL removed; chart of accounts and
  debt-repayment posting rules defined in 001; reproducible provider-rate seed (never
  `GatewayModel` floats); deferred-trigger balanced postings; idempotency = operation ID
  + request hash; durable worker framework moved to 001 (webhooks/scheduled
  grants/outbox need leases + SKIP LOCKED, not lifespan tasks); publication decoupled
  from Stripe bindings (bindings gate activation — kills the 002↔006 cycle);
  non-overlapping assignment intervals + atomic account-creation assignment; 004
  deny-by-default route/SKU framework, `X-Luna-*` header stripping, exposure from actual
  input + output ceiling, namespaced correlation IDs, full billing-identity token
  verification; H3 chargeability wording; Luna audit B1–B4/H1–H6 (explicit pydantic-ai
  models + httpx hooks spike, `ProviderPolicyBlockedError` in phase 1 before fallback,
  root-action mint table, HookedModel wraps FallbackModel, expanded caller inventory,
  provider support matrix, `policy_blocked` AgentEvent, block contract frozen in 004,
  Forge tagging deferred); 005 transactional/durable Luna provisioning, hosting-state
  guard on all wake paths, soft-delete agents, no machine/volume double-charge, anchor
  day clamping, stale-hold → `needs_reconciliation`; 006 portal plan-switching disabled,
  `CLOUD_STRIPE_*` names + livemode checks, corrected key permissions/events, tax
  treatment per product class; 007 code-owned upgrades (`pending_if_incomplete`),
  per-lot compound idempotency keys, `invoice.paid` validation, annual-lot calendar
  arithmetic + activation worker, proportional refund/dispute clawback, auto-top-up SCA
  state; **M6 decided:** launch dunning has no credit grace — failed renewal blocks,
  top-ups allowed while past due; 008 honest block taxonomy (customer- vs
  operator-actionable), recovery payload, server-side owner-role check, dynamic public
  pricing page (static Free/$29/$99 page contradicts v1); 009 run manifests,
  decimal-string transforms, deterministic replay ordering, funding modes, Stripe cash
  reconciliation, thresholded debt alerts, hard 007 dependency; 010 reordered rollout
  (live payment recovery and compatible Luna image before any customer enforcement),
  per-account enforcement override, honest reversibility wording, no data deletion for
  nonpayment; **M9 settled (owner, 2026-07-13):** migrated accounts get exactly the
  trial treatment — flat 1,800 gift (configurable, versioned product), one active Luna.
  The most recently active Luna stays running (999 charged, hosting period opened);
  every other running Luna is stopped at migration, data retained, normal 999 restart
  later. Sol's `999 × N + 801` multi-Luna formula was superseded by this decision.
  `cutover_at`; customer notice before migration; signed dry-run manifest.
  Not adopted: Sol's block/reject verdicts as process (plans amended instead, not
  frozen); full customer marketplace schema/UX inside 039 (marketplace stays disabled
  and gets its own plan — only entitlement/refund policy recorded); the maximal
  simulation manifest (trimmed: no git SHA or per-row hashes — event-ID-list hash +
  config/algorithm versions suffice); mobile/screen-reader dojo scenarios as gating
  criteria; full alert ownership/escalation/runbook taxonomy (threshold, severity,
  dedupe kept; incident process is out of 039's scope).

## Recommendation

All high findings (H1–H5) are resolved and folded into the phase plans; M6, M8, and M9
are decided. Proceed with phase 001. Remaining owner decisions before their gating
phases: exact LLM constants (before publishing version 1), non-LLM SKU prices (before
enabling those SKUs), and the authorization latency budget (M4, before enforce).
