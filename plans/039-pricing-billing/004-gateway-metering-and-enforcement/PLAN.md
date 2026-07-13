# 039/004 — Gateway metering and hard enforcement

**Parent:** `plans/039-pricing-billing/PLAN.md` (Phase C)
**Depends on:** 001 (billing service), 002 (versions/assignments). 003 improves
classification but is not a blocker — missing metadata rates as `agent`.

## Objective

Make every platform-keyed gateway request billing-grade: hold before upstream, one
`billable_event` per provider attempt, rate per logical call with the snapshotted
versions, settle or reconcile. Enforcement obeys `CLOUD_BILLING_MODE`.

## Amendments from phase 001 (2026-07-13)

- The ledger already emits distinct typed failures: `InsufficientBalance` (posted
  balance ≤ 0), `ExposureLimit` (single bounded overrun cap exceeded), `LimitExceeded`
  (per-Luna daily/monthly). The gateway must map each to its own block code
  (`credits_exhausted` / `exposure_limit` / `luna_daily_limit` / `luna_monthly_limit`) —
  they are different customer situations. Note the overrun semantics: one hold *may*
  exceed available balance within `overrun_cap_credits` (default 1,000) by design; only
  balance ≤ 0 or cap breach blocks.
- Hold/settle/release, `needs_reconciliation` stale-hold semantics, and idempotent
  authorize (operation ID + canonical request hash; same ID + different hash =
  `IdempotencyConflict`, never a dedupe) are implemented in `cloud/billing/ledger.py` —
  build the gateway path on those functions, not new ledger code.
- Durable settlement/reconciliation work goes through `cloud/billing/worker.py`
  (`billing_outbox`); register handlers, never `asyncio.create_task` for financial work.
- Any Python-side comparison of DB-loaded timestamps must normalize naive→aware
  (`_aware()` pattern; SQLite returns naive, Postgres aware) or compare in SQL.

The current gateway forwards arbitrary methods and paths under a real platform key —
model checking alone does not stop expensive unsupported endpoints (batches, files,
fine-tuning, future provider APIs). This phase owns the route/SKU framework:

- Managed gateway traffic is deny-by-default by `(service, method, normalized path)`.
  Each allowed route maps to exactly one adapter and SKU. Unknown routes return
  `sku_unpriced` before any upstream contact in enforce mode; observe/shadow record the
  would-block decision. 005 adds non-LLM adapters through this framework rather than
  duplicating enforcement.
- All internal `X-Luna-*` headers are stripped before the upstream request — they must
  never reach a provider.
- Tenant token verification resolves the full billing identity: active account, agent
  state, hosting/payment state — not just an agent ID. Revoked, deleted, blocked, and
  payment-due agents cannot spend.

### Provider adapters and correlation

- Billing-grade usage parsing per provider (replaces regex `UsageScanner` as financial
  source): normal/cached input, cache creation, output/reasoning, audio/image,
  embeddings, service tiers, batch discounts — without double counting provider totals.
- Logical-call/attempt correlation from Luna headers; gateway-generated IDs when absent.
  Tenant-supplied correlation IDs are untrusted: they are namespaced by authenticated
  agent plus request fingerprint, and reuse with different immutable request facts
  (account, body hash, model) is rejected — never deduplicated into a skipped charge.
- Provider request/response IDs captured; SSE stream capture tolerant of chunk splits;
  stream settlement is written durably (outbox), not only in an in-process `finally`
  that dies with the process.

### Context and rating

- Context resolution: `forge` from job-scoped token; advisory agent/direct header;
  default `agent`. Model tier resolved from the requested model against the version's
  top/mid lists.
- Rate: sum billable attempt costs in micro-USD via the snapshotted provider-cost
  version, add the context/tier constant once, one final `ceil`.
- Chargeability (resolves review H3, gateway-side definition): a call is
  customer-chargeable once the gateway has initiated accepted provider work and receives
  a successful billable response or billable usage. Tenant cancellation, disconnect,
  timeout, or discarding the result never converts provider spend into Luna-absorbed
  cost. Absorption is limited to provider/platform failures that produced no usable
  provider result; that failed-attempt provider cost is recorded as Luna-absorbed on the
  rated charge.

### Enforcement path

- Authorize hold before contacting the provider. Exposure = actual serialized input plus
  the requested maximum output under the snapshotted tariff — not the model's entire
  context window. When no output maximum is present, the gateway applies a configured
  output ceiling; authorization enforces that ceiling so maximum uncovered liability
  stays within the overrun cap. Machine-readable block returned without provider
  contact.
- Mode semantics: `off` bypasses billing; `observe` records events/ratings without
  wallet decisions; `shadow` executes decisions against an isolated shadow wallet with
  no customer effect; `enforce` holds, blocks, and settles. Billing-store failure fails
  closed only in enforce mode.
- Settle full real charge and release remainder; disconnect after provider spend →
  `needs_reconciliation`, never silent release.
- Stable block contract: `credits_exhausted`, `luna_daily_limit`, `luna_monthly_limit`,
  `hosting_payment_due`, `sku_unpriced`, `exposure_limit`,
  `billing_temporarily_unavailable`.
- Legacy `usage_events` dual-write during transition (telemetry only).
- Provider usage reconciliation worker + unresolved-operation reaper.
- Migrate or disable `key_mode=env` / `LEGACY_REAL_KEY_VARS` paths (Tavily review point)
  before enforce mode — a real key on the tenant machine is an unmeterable bypass.
- Fresh ledger/limit reads on authorization; never the short-lived auth/account cache.

## Tests first

- Provider fixtures for every enabled model: all usage dimensions, SSE chunk splits,
  missing/duplicate usage frames.
- Every managed method/path is classified before upstream contact; an unknown endpoint
  never reaches upstream in enforce mode.
- Internal `X-Luna-*` headers never reach providers.
- Same logical ID with altered account/body/model cannot dedupe a charge.
- Client disconnect after provider acceptance remains chargeable/reconcilable.
- Process death at each pre-send/post-send/usage-event/settlement boundary → exactly one
  explainable state.
- Mode matrix off/observe/shadow/enforce, including billing DB failure in each mode.
- Alias and provider-returned model canonicalization.
- Revoked, deleted, blocked, and payment-due agents cannot spend.
- Duplicate provider/request IDs never double-charge.
- Spoofed account/Luna headers cannot change attribution; spoofed model/forge claims
  cannot change verified tier/context; claimed `direct` is the only tenant-influenced
  discount and is bounded by the constant spread.
- Timeout, disconnect, cancellation, fallback, restart → exactly one explainable state
  (`blocked|released|settled|needs_reconciliation`).
- Fallback attempts add at most one margin per successful logical call.
- No prompt/output/credential enters billing data.
- Concurrent calls respect balance, exposure cap, and per-Luna limits.
- Unknown model/context/service fails closed only in enforce mode.

## Exit criteria

- Every platform-keyed gateway request ends `blocked`, `released`, `settled`, or
  `needs_reconciliation`.
- Reconciliation tooling works against provider sandbox/short-window data. Reconciling a
  complete provider billing period is a rollout gate (010), not a code-phase exit
  criterion.
