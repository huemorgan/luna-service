# 039/008 — Customer credits and usage dashboard

**Parent:** `plans/039-pricing-billing/PLAN.md` (Phase F)
**Depends on:** 005 (statements/limits), 007 (products/checkout/portal), and 003/004 for
hosted block rendering — the dojo block scenarios require the compatible Luna image.

## Objective

A customer can understand every balance change and recover from every
**customer-actionable** block without admin help. Operator/system states
(`sku_unpriced`, `billing_temporarily_unavailable`, and `exposure_limit` while holds
drain) show a truthful retry/status path and never claim payment will fix them. Credits
only — no internal dollars, margins, pricing contexts, or model tiers anywhere.

This phase owns the full parent-plan customer billing API surface (balance, grants,
products, usage detail, statements, invoices, limits, Checkout/Portal session creation,
CSV) — the UI relies on no unspecified routes. Account and role are derived server-side:
owner-only mutations do a fresh membership-role check and return 403 to non-owners even
on direct API calls (`require_active_account` currently never checks `Membership.role`).

## Deliverables

### Navigation and credits page

- `/dashboard/billing` + visible `Credits & usage` header entry; agent cards link to
  filtered per-Luna usage; `AgentDetail` replaces "Spend — coming soon" with real data.
- Credits page: total posted balance (red at ≤ 0), held/open exposure shown separately,
  bonus/paid/top-up/gift balances with exact expirations and "use next" order, current
  bucket + renewal date, annual future scheduled lots, top-up steps, upgrade action,
  scheduled downgrade/cancellation state, trial status and days remaining,
  low-credit/debt/failed-payment notices, invoices via Stripe.
- Recovery payload rendered wherever a block or debt appears: `debt_credits`,
  `credits_required_for_positive_balance`, `hosting_restart_credits` (a stopped Luna
  shows the total to clear debt **and** buy its next 999-credit period),
  `next_payment_retry_at`, `payment_action_required`, `open_exposure_credits`, and the
  exact recommended action.
- Public marketing pricing: replace the hardcoded Free/$29/$99 tiers in
  `cloud/ui/src/marketing/pages/Pricing.tsx` with `GET /api/public/pricing` from the
  published new-account version — 28-day trial, Hobby 19, Recurring 100/200, yearly
  variants, top-up steps. Remove "degrades gracefully" copy that contradicts hard
  blocking.

### Usage dashboard

- Ranges: today, 7 days, 28 days (default), custom.
- Summary: used/remaining, today/current month, upcoming expiration, per-Luna usage and
  limit progress, trend + projected depletion clearly labeled an estimate.
- Breakdowns: Luna; service category; service/plugin; action type (chat, playbook run,
  scheduled/background run, forge job — functional dimensions from root-action metadata,
  never the internal pricing context); model; root action.
- Action statement: time, Luna, human label, service, status, integer credits;
  expandable child events for multi-call actions; running balance; filters + CSV export.

### Limits and roles

- Owner sets nullable per-Luna daily/monthly limits; settled + open exposure, reset
  timestamp, warning threshold shown. Hosting consumption is excluded from limit
  progress.
- Non-owner members view usage; cannot change billing, payment, or limits.

### Block handling

- All gateway block codes render directly (`credits_exhausted`, `luna_daily_limit`,
  `luna_monthly_limit`, `hosting_payment_due`, `sku_unpriced`, `exposure_limit`,
  `billing_temporarily_unavailable`) with the required action; never via another LLM
  call. Customer-actionable codes show the payment/limit action; operator/system codes
  show status and retry guidance, truthfully.

Marketplace customer UX (offers, purchase confirmation, entitlement state, history) is
out of scope here — marketplace charging is disabled at launch and gets its own plan
once the offer/purchase/entitlement schema exists (see 005/010).

## Dojo walkthrough (browser, required)

- Trial signup shows the gift balance and expiry; exhausted/expired trial blocks paid
  work; subscribing to Hobby restores it.
- Subscription shows paid + bonus separately; bonus spends first.
- Yearly subscription shows the monthly lot pacing and the yearly gift.
- Multi-call chat groups child charges under one action.
- Luna A hits its cap while Luna B continues.
- 5-credit balance completes a 10-credit action → −5 in red → next action blocked →
  top-up clears debt and restores paid work.
- Paid hosting persists to period end, then stops on failed renewal.
- Debt recovery where a top-up clears debt but remains below the 999 restart
  requirement shows the remaining amount truthfully.
- Failed renewal → payment method update → later paid invoice → grant and restart.
- Non-owner cannot mutate limits or payment — verified at the API (403), not just
  hidden buttons.
- Back/refresh/replayed browser return never grants or duplicates payment.
- Marketing pricing page equals the published new-account catalog.
- No customer surface — API, CSV, DOM, logs, statements — reveals internal dollars,
  margin, pricing context, or model tier.

## Exit criteria

- Every dojo scenario passes in the browser; the customer path from every
  customer-actionable block to recovery needs no admin intervention, and
  operator-actionable states are honestly labeled.

## Amendments from phase 002 (2026-07-14)

- Dojo harness exists and is reusable: `tests/039-pricing/dojo_admin_ui.py` —
  dedicated Postgres DB (docker PG :5435) + `python -m cloud.db.migrate` +
  uvicorn with background loops disabled, a minted `luna_session` cookie
  (itsdangerous, dev secret), Playwright headless chromium, screenshots +
  PASS/FAIL report under `tests/039-pricing/results/<date>-local/`. Write the
  008 customer scenarios as a sibling script; only block-rendering scenarios
  need the compatible Luna image.
- UI conventions confirmed in 002: `verbatimModuleSyntax` is on — interface
  imports must be `import type`; any file containing JSX must be `.tsx`;
  coerce FastAPI 422 detail arrays with the shared `apiError()` pattern.
- Customer billing mutation routes must take `Depends(enforce_same_origin)`
  like the admin pricing router — the dependency exists in `cloud/auth/deps.py`
  and absent-header (non-browser) clients still pass.

## Amendments from phase 004 (2026-07-14)

- Customer-visible usage reads `rated_charges` (+ `billable_events` for
  attempt detail). The `rule_snapshot` field set is now stable:
  context/tier/sku/margin/models/estimated_credits/status_code/usage_missing/
  would_block/unrated_dimensions. **Never expose context, tier, margin, or
  micro-USD fields to customers — credits and model names only** (billing
  rows themselves contain no prompts/outputs/keys; tested).
- Block-state UX must match the frozen 402 contract (codes + `retryable`
  flag; see 003 amendments). `credits_exhausted`, `luna_daily_limit`,
  `luna_monthly_limit`, `hosting_payment_due` are customer-actionable;
  `sku_unpriced`, `exposure_limit`, `billing_temporarily_unavailable` are
  operator states and must be labeled honestly as such.
- For dojo scenarios that need real gateway traffic (usage rows, blocks),
  reuse `dojo_gateway_billing.py`'s mock-upstream + per-mode app boot instead
  of a live provider; drive the browser against the same scratch PG.

## Amendments from phase 005 (2026-07-14)

- Hosting is now customer-visible data: show the current period
  (starts/ends, 999 credits) per Luna, `payment_due` as a prominent
  "restart to pay" CTA (the start endpoint is the payment action), and
  upcoming renewal date (monthly anchor, clamped).
- Grants list: trial gift (1800, 28-day expiry) and admin gifts carry
  `expires_at` — show expiring credits distinctly; expired grants are
  swept by maintenance, not silently rewritten.
- Soft-deleted Lunas: excluded from agent lists but their hosting charges
  and usage remain in billing history — the UI must resolve agent names
  for tombstoned agents (query without the `deleted_at IS NULL` filter
  for display purposes only).
- Trial state for the UI = absence of paid-source grants; surface "trial"
  badge + 1-Luna cap message from the same rule the backend uses.
