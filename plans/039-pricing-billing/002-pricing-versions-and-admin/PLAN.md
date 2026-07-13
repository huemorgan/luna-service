# 039/002 — Pricing versions, assignments, and admin pages

**Parent:** `plans/039-pricing-billing/PLAN.md` (Phase B)
**Depends on:** 001 (schema, version core)

## Objective

Make pricing operable: draft/clone/validate/publish workflow, account assignments,
rollout engine, and the admin Pricing section. Still no Stripe money and no production
debits.

## Amendments from phase 001 (2026-07-13)

- The version domain core already exists: `cloud/billing/versions.py` implements schema-v1
  validation (recursive float rejection, fixed credit value, paid==payment invariant, dup
  key checks), canonical sha256 hashing, draft→publish with tamper check, and
  `assert_mutable`; `cloud/billing/seed.py` seeds version 1 and provider-cost v1. This
  phase builds the admin API + UI + assignments/rollouts **on top of** that module — do
  not reimplement validation in routes.
- Published-version immutability and published→retired-only transitions are additionally
  enforced by Postgres triggers from migration 0002. Admin routes must still return clean
  400s from the service layer; the triggers are the backstop, not the error UX (trigger
  errors surface at COMMIT as raw DB exceptions).
- SQLite tests do not run the triggers — service-layer checks are the only enforcement
  there, so every immutability rule needs an API-level test, not just a trigger test.
- Test convention: no module-global asyncio pytestmark; mark async tests individually
  (sync tests under a global mark emit warnings).

## Deliverables

### Version workflow

- Clone published commercial version → draft; edit draft only; saving never touches a
  published version.
- Validation on publish:
  - credit value unchanged (read-only field);
  - paid credits exactly equal payment × 100 (yearly: total across the 12 lots);
  - top-ups have no bonus;
  - every enabled SKU has a complete nonnegative rule; every context/tier has a constant;
  - top/mid model tier lists are disjoint and cover all enabled models;
  - burn/expiration policies deterministic;
  - no rule permits unbounded in-flight exposure.
- Commercial publication validates portable product keys and economics only. Stripe IDs
  live in environment-specific binding rows; missing bindings block environment
  activation, checkout, and live promotion — not publication. (This breaks the 002↔006
  circular dependency: 006 consumes the validated draft catalog, enters bindings, then
  checkout activates.)
- Publication freezes JSON + hash permanently; canonically equivalent JSON produces the
  same hash; immutable diff and audit history.
- `gateway_models` (`tier`, `input_cost`, `output_cost`) is routing/catalog metadata
  only — never read by authorization, rating, reconciliation, or simulation. Commercial
  tier lists and provider costs come exclusively from snapshotted versions. Enabling a
  new global gateway model does not make it billable under a published version that has
  no tier/rule for it — it fails closed (`sku_unpriced`) until a version covers it.

### Assignments and rollouts

- Assignments are non-overlapping effective intervals per account — no gaps for an
  authorized account, no overlaps, enforced at the DB. A separate effective-dated
  default determines new-account assignment; account creation (`auth_routes.py`) inserts
  the billing account and its assignment in the same transaction.
- Authorization snapshots the account's commercial version and the globally effective
  provider-cost version.
- Rollout audiences: `new_accounts`, `all_accounts`, `selected_accounts` (canary), with
  scheduled/applied/failed counts and audit. An `all_accounts` rollout stores both the
  runtime assignment work and the pending per-subscription renewal migration intent
  (consumed by 007); completion requires both.
- Rollback = scheduling a prior published version as a future assignment.
- Provider-cost publication is global and effective-dated; never cohort-pinned.

### Admin UI (management left pane, collapsible `Pricing` section)

- **Overview** — active/default version, customer liability, debt, failed billing work.
- **Versions** — clone/edit/validate/publish/promote, rollout status, immutable diff.
- **LLM & services** — agent/direct/forge constants by model tier, top/mid tier lists,
  provider-cost versions, SKU catalog editor (dynamic JSON list), hosting price,
  unpriced-SKU warnings.
- **Credit buckets** — trial gift, Hobby/Recurring monthly + yearly products, top-up
  steps, expiration, burn order, Stripe binding placeholders.
- Every mutation: admin auth, before/after audit, actor, reason where financial,
  server-side validation, and an explicit CSRF mechanism (current cookie-authenticated
  admin mutation routes have none — add origin/token checking, not just a label).

## Tests first

- Edits create/modify a draft, never a published version.
- Calls in flight keep both snapshotted versions even if a publication happens
  mid-stream.
- `new_accounts` leaves existing accounts pinned; `all_accounts` changes only future
  charges after the effective time.
- Provider-cost publication applies globally and cannot be cohort-pinned.
- Rollback creates assignment history; nothing historical is edited.
- Account created during a rollout receives exactly one assignment at the DB effective
  timestamp; rollout restart neither skips nor duplicates accounts.
- Assignment intervals cannot overlap or leave an authorized account unassigned.
- Editing `GatewayModel.input_cost`, `output_cost`, or `tier` cannot alter any charge.
- Enabling a new gateway model cannot make it billable under an unpriced active version.
- Cross-origin admin mutation is rejected.
- Enabled unpriced SKU cannot publish; disabled SKUs skip the pricing-rule check.
- Tier list validation rejects a model present in both tiers or in neither.

## Exit criteria

- A version moves draft → validated → published → canary/new/all assignment with a full
  audit trail, without collecting any money.
