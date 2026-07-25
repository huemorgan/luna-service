# 061 — In-flight exposure hold leak (credits visible but "spending in flight")

**Status:** primary fix SHIPPED (overdraft + exposure guard removed) · reconciler
follow-up open · **Severity:** P0 (production, silently locks paying accounts out
of all paid work while their balance looks healthy)

## SHIPPED (this change)
The exposure guard that caused the block is **removed**, and LLM admission now
runs on an **overdraft floor** instead of holds/exposure — owner decision, better
customer experience ("better they overdraft and owe us than be stranded"):
- `ledger.authorize()` no longer computes `open_exposure`/`available` and no
  longer raises `exposure_limit`. It admits paid work while
  `posted_balance > -OVERDRAFT_LIMIT_CREDITS`, then raises `credits_exhausted`
  ([cloud/billing/ledger.py](../../cloud/billing/ledger.py) `authorize`).
- `OVERDRAFT_LIMIT_CREDITS` defaults to **2000 credits ($20)**, tunable in prod
  via env `CLOUD_OVERDRAFT_LIMIT_CREDITS` — the only bound on a runaway.
- Per-agent daily/monthly limits are **unchanged** (still enforced). Hosting is
  **unchanged** (its balance checks and suspend flow stand — "machine is fine").
- Holds are still created as the settle vehicle but no longer reserve/block, so a
  leaked `needs_reconciliation` hold can no longer strand an account. This makes
  the leak non-user-impacting; the reconciler below is now cleanup, not urgent.
- Tests updated to the new policy; full cloud suite green (728 passed).

**Still open (follow-up, no longer P0):** the hold reconciler (Fix 1) to keep the
admin `needs_reconciliation` count from growing cosmetically; physically dropping
LLM hold creation entirely (Fix 2 direction); Fix 0 to reconcile the live
`vaselin` account's already-leaked holds (its block is now moot under overdraft,
but the stale holds still show in ops).

---


## Symptom (observed in prod)

`vaselin` account, machine `https://luna.com.ai/a/vaselin-gamer/p/marketplace`.
Dashboard shows **Total Account Credits 1,407** ("1,407cr / 41,000cr left"), yet
sending any message is rejected:

> ⛔ Message not processed — **Too much spending is in flight for this
> workspace. Retry once current work settles. You can try again later.**

The account has a running Luna (`RayLa`) and a stopped one (`PA`). The wallet is
**not** empty, so this is **not** `credits_exhausted`. It is the **`exposure_limit`**
block — a concurrency/reservation guard, not a balance guard.

## Root cause (confirmed against source)

The block string is the frozen `exposure_limit` 402 code
([enforcement.py:67](../../cloud/gateway/enforcement.py#L67)); it is retryable
([enforcement.py:70](../../cloud/gateway/enforcement.py#L70)), which is where the
"You can try again later" tail comes from.

It is raised by the availability guard in `ledger.authorize()`
([ledger.py:783-810](../../cloud/billing/ledger.py#L783-L810)):

```python
balance = await posted_balance(session, account_id)          # 1,407 — the visible number
if balance <= 0: raise InsufficientBalance(...)              # would be credits_exhausted, NOT our error
open_holds = ... BillingHold.status.in_(["open", "needs_reconciliation"]) ...   # 787-794
open_exposure = sum(h.estimated_credits for h in open_holds) # the "spending in flight"
available = balance - open_exposure                          # 796  <-- guard blocks on THIS
overrun = max(estimated_credits - max(available, 0), 0)
if overrun > 0:
    if available <= 0:
        raise LimitExceeded("exposure_limit", "concurrent work requires positive availability")
    ...
    if overrun > acct.overrun_cap_credits:                   # cap default 1000 (models.py:196)
        raise LimitExceeded("exposure_limit", ...)
```

**The guard operates on `available = balance − open_exposure`, never on the
balance the dashboard shows.** A `BillingHold` is a reservation opened *before*
each provider call; it posts nothing to the wallet, so it is invisible on the
balance but fully counted here.

### Why `open_exposure` grows and never shrinks (the actual defect)

`needs_reconciliation` holds count toward exposure **forever**
([ledger.py:640-642](../../cloud/billing/ledger.py#L640-L642),
[ledger.py:791](../../cloud/billing/ledger.py#L791)), and **nothing automatically
resolves them.** Three leak paths feed that bucket:

1. **`usage_missing` finalize never enqueues a settle/release job.** When a
   provider returns `<400` with no parseable usage, the charge is written as
   `needs_reconciliation` ([enforcement.py:397-406, 441](../../cloud/gateway/enforcement.py#L397-L406))
   and the enqueue is explicitly skipped by `and not usage_missing`
   ([enforcement.py:473](../../cloud/gateway/enforcement.py#L473)). The hold is
   left "for the reaper" — but the reaper only downgrades, it never settles.

2. **Process/stream death before the finalize commit.** The `finalize()` body is
   best-effort and swallows on failure
   ([enforcement.py:486-490](../../cloud/gateway/enforcement.py#L486-L490)),
   leaving the hold `open` for the reaper.

3. **The stale-hold reaper is one-way.** `mark_stale_holds` moves `open` holds
   past their 30-min TTL to `needs_reconciliation` and stops there — "never
   silently released and never silently settled"
   ([ledger.py:958-976](../../cloud/billing/ledger.py#L958-L976),
   reaper pass [enforcement.py:534-539](../../cloud/gateway/enforcement.py#L534-L539)).

The `gateway_finalize` job handler *can* settle a `needs_reconciliation` hold
with its rated amount ([enforcement.py:493-527](../../cloud/gateway/enforcement.py#L493-L527)),
**but no code path ever enqueues that job for a leaked hold.** The only places
that even acknowledge the bucket are read-only: an admin count
([billing_admin_routes.py:140](../../cloud/api/billing_admin_routes.py#L140)),
the Pricing Ops page, and a 4-hour warning alert
([operations.py:513](../../cloud/billing/operations.py#L513)). There is **no
automatic reconciler for billing holds** (`runtime/reconcile.py` is Fly
machine-status only, unrelated).

**Net:** every request that dies mid-stream, restarts a worker, or hits the
`usage_missing` branch leaks a permanent reservation. On a busy account these
accumulate until `open_exposure ≈ balance`, `available ≤ 0`, and *every*
subsequent paid call trips `exposure_limit` — with the wallet still showing a
full balance.

### Interaction with running/stopped machines (user's hypothesis)

Directionally correct, mechanism subtler. Machines don't hold a standing
per-machine reservation against the whole balance. But:

- Each running Luna's in-flight LLM calls each open a short hold; a call that
  dies mid-stream leaks per paths 1–2.
- **Hosting holds are the sharpest suspect.** `hosting.py` opens a hold for a
  full month's hosting price with a 30-min provision TTL
  ([hosting.py:167-179](../../cloud/billing/hosting.py#L167-L179)), settled only
  when provisioning confirms. A stalled/crashed provision (plausibly the
  **`PA` Stopped** machine) leaves a *large* hold that the same one-way reaper
  parks in `needs_reconciliation`. `open_exposure` sums holds by status only —
  `count_toward_limits=False` does **not** exclude them from the account
  availability guard — so a single leaked hosting hold can drive `available`
  negative on its own.

`41,000cr` is consistent with a **per-Luna monthly limit** (a different check,
[ledger.py:812-833](../../cloud/billing/ledger.py#L812-L833)), not this guard —
which is why that number looks fine while the account is still blocked.

## Fixes

### Fix 0 — Unblock the live account NOW (operational, no deploy) — **P0**
The `vaselin` account is locked in prod today. Immediate remediation:

1. **Diagnose:** list this account's `BillingHold` rows in `open` /
   `needs_reconciliation` (age, `estimated_credits`, `operation_id`,
   `count_toward_limits`, matching `RatedCharge.charge_status`). Confirm
   `open_exposure` vs `posted_balance` and which holds dominate (expect one or
   more stale `hosting:{period.id}` or dead gateway holds).
2. **Resolve each leaked hold** through the existing idempotent handler rather
   than by hand-editing rows: enqueue a `gateway_finalize` job (`settle` with the
   already-written `RatedCharge.credits`, or `release` if none/zero) per
   `operation_id` — `_handle_gateway_finalize` already settles
   `needs_reconciliation` holds correctly
   ([enforcement.py:493-527](../../cloud/gateway/enforcement.py#L493-L527)). For
   leaked **hosting** holds with no rated charge, `ledger.release`.
3. **Verify** `available` returns positive and the account can send. Keep the
   diagnostic output — it is the ground truth for scoping Fixes 1–3.

Do this via a one-off reconcile invocation (the same code Fix 1 productizes),
**not** raw SQL, so it stays idempotent and audited. Ship Fix 1 right after so it
doesn't silently re-accumulate.

### Fix 1 — Automatic reconciler for stuck holds — **P0, the durable fix**
Add a periodic sweep (a billing-worker job or a loop under `LOCK_RECONCILER`'s
sibling, single-flighted via `run_exclusive`) that resolves holds the reaper only
downgraded:

- For each `needs_reconciliation` hold older than a grace window: if a
  `RatedCharge` exists for its `operation_id`, enqueue/settle with
  `charge.credits`; else `release`. Reuse `_handle_gateway_finalize` semantics so
  it stays idempotent and replay-safe.
- Add a hard ceiling on hold age (e.g. release/settle anything older than N hours
  regardless) so exposure can never grow unbounded again.
- Emit a metric per resolution and wire the existing 4-hour alert
  ([operations.py:513](../../cloud/billing/operations.py#L513)) to fire only when
  the reconciler itself is failing, not merely when the bucket is non-zero.

### Fix 2 — Close the `usage_missing` enqueue gap — **P1**
On the `usage_missing` enforce branch, stop leaving the hold dangling: enqueue a
`gateway_finalize` `settle` for the estimated/rated credits (or `release` if
zero) instead of skipping enqueue at
[enforcement.py:473](../../cloud/gateway/enforcement.py#L473). This removes the
single largest structural leak so Fix 1 becomes a backstop, not the primary
mechanism. Preserve the "never silently settle real provider spend" intent by
settling the **estimated** amount and flagging the charge for later audit rather
than dropping it.

### Fix 3 — Stalled hosting-hold safety — **P1**
Guarantee every `hosting:{period.id}` hold is settled or released on a bounded
timeline even when provisioning stalls/crashes (tie release to the
machine/provision terminal state so a `Stopped`/failed provision can't leave a
month-sized reservation open). Verify against the `PA` machine found in Fix 0.

### Direction (owner decision) — drop LLM holds, guard with overdraft instead
Preferred approach: **stop opening holds for LLM/provider calls entirely.** Charge
each call on settle (post-hoc) and let the balance ride into a bounded overdraft
(Fix 4) instead of reserving up front. This deletes the whole leak class — no
LLM hold can leak because none exists. Keep the hosting provisioning hold (it's
fine). Accepted trade-off: without a real-time reservation, a burst of concurrent
calls can overshoot the overdraft cap by ~(parallel calls × per-call cost) before
settlements land; bounded and small for a single agent; the overdraft cap still
hard-blocks new calls once crossed. This reframes Fixes 1–2 as mostly moot for
LLM calls (still needed for the hosting hold) and makes Fix 4 the primary guard.

### Fix 4 — Allow a small overdraft instead of hard-blocking — **wanted (product decision)**
**Rationale (owner):** it is better to let a user spend down to a small negative
balance and owe us than to strand them with a few credits they can't use. A tiny
overdraft buffer avoids the "1,407 credits but can't send" dead-end even after the
leak (Fixes 0–3) is closed.

**Where it bites today (two separate gates, both must allow the buffer):**
- Hard balance floor: `if balance <= 0: raise InsufficientBalance`
  ([ledger.py:784-785](../../cloud/billing/ledger.py#L784-L785)) — surfaces as
  `credits_exhausted`.
- Availability floor: `if available <= 0: raise LimitExceeded("exposure_limit")`
  ([ledger.py:800-803](../../cloud/billing/ledger.py#L800-L803)) — the guard in
  this plan.

**Shape:** introduce a per-account `overdraft_limit_credits` (default small, e.g.
a few hundred; column on the billing account like `overrun_cap_credits` at
[models.py:196](../../cloud/billing/models.py#L196)). Change both floors from
`<= 0` to `<= -overdraft_limit` so balance/availability may dip to `−limit`.
Debt already exists as a concept — `create_grant` repays outstanding debt
([ledger.py](../../cloud/billing/ledger.py)) — so a negative wallet must post as
recoverable debt and be netted against the next grant/top-up, not silently
forgiven. Decisions to make: does overdraft apply to LLM usage, hosting, or both;
does hitting the overdraft trigger auto-topup/dunning; per-account vs per-tier
default. **Do this only after Fixes 0–3** so the buffer isn't immediately eaten by
leaked holds. Tie the sizing to the hosting-cost decision in the note below.

### Fix 5 — Make the block state observable to the user & operator — **P2**
Today the only signal is a raw 402 string. Surface `available`, `posted_balance`,
and `open_exposure` together (dashboard "credits" tile is misleading when
exposure is high), and expose per-account leaked-hold detail on the Pricing Ops
page so this is diagnosable without a DB session.

## Hosting cost model — already implemented (context for Fix 4)
The "flat monthly fee, machine rented until X, same price open or closed" model
**already exists** and does not need to be built:
- 999 credits = **$9.99/month** per Luna ([versions.py:19](../../cloud/billing/versions.py#L19),
  [seed.py:67-68](../../cloud/billing/seed.py#L67-L68); 1 credit = $0.01).
- `AgentHostingPeriod` with `starts_at`/`ends_at` = the rental window
  ([models.py:456-486](../../cloud/billing/models.py#L456-L486)); auto-renews
  **in advance** via `renew_due_periods()`
  ([hosting.py:338-419](../../cloud/billing/hosting.py#L338-L419)).
- **Decoupled from run state:** stopping/sleeping a Luna does NOT reduce the
  charge; `stop_agent` never touches hosting
  ([agent_routes.py:439-474](../../cloud/api/agent_routes.py#L439-L474)); renewal
  ignores `Agent.status`. Off or on, the month is billed. Early delete forfeits
  the remainder (no proration, [hosting.py:317-333](../../cloud/billing/hosting.py#L317-L333)).
- Paid from the **same credit wallet** as usage (not a separate Stripe sub;
  Stripe only tops up credits); excluded from per-Luna usage limits
  (`count_toward_limits=False`, [hosting.py:176](../../cloud/billing/hosting.py#L176)).

Two implications for this plan:
1. The **first-month provisioning hold** (`hosting:{period.id}`) is the only
   hold-based part of hosting and is a prime leak in Fixes 0/1/3 — a stalled
   provision parks a month-sized hold in `needs_reconciliation`. After month one
   it is a clean debit, no hold.
2. **Overdraft (Fix 4) ties directly to hosting renewal.** Today an unaffordable
   renewal flips the period to `payment_due` and *suspends the machine*
   ([hosting.py:374-389](../../cloud/billing/hosting.py#L374-L389)). The desired
   behavior is to let the $9.99 push the balance to a small negative (debt) and
   keep the Luna alive instead of suspending — decide whether overdraft covers
   hosting renewals, usage, or both, and how debt is recovered on next top-up.
   Run-state-driven hosting *discounts* (pay less while asleep) are explicitly
   **out of scope** (owner wants flat "off still pays"); plan 059's sleep work
   only cuts idle LLM/compute spend, not the hosting fee.

## Diagnostics to capture before/after
- `posted_balance`, `open_exposure`, `available`, `overrun_cap_credits` for the
  account.
- Hold inventory by status/age/`operation_id`, joined to `RatedCharge.charge_status`.
- Fleet-wide: count + credit sum of `needs_reconciliation` and stale `open` holds
  across all accounts (this bug is almost certainly not unique to `vaselin`).

## Verification
1. Fix 0: `vaselin` sends successfully; `available > 0`.
2. Fix 1/2: synthetically leak a hold (kill a stream mid-finalize; force a
   `usage_missing` finalize) → reconciler settles/releases it within the grace
   window; `open_exposure` returns to steady state; no `exposure_limit` on an
   account with positive balance and no genuine concurrent overrun.
3. Fleet sweep: `needs_reconciliation` credit sum trends to ~0 and stays bounded.
4. Regression: legitimate concurrency limiting still works — an account with
   genuine simultaneous in-flight work over `overrun_cap` still blocks.

## Risk
- Fix 0 mutates live billing state — only settle with the **already-rated**
  charge amount or release uncharged holds; never invent charges; keep it
  idempotent (the `gateway_finalize` handler already is) and audited.
- Fix 2 must not settle **real** provider spend at a wrong amount — settle the
  recorded estimate and mark for audit; don't silently zero it.
- The reconciler must be single-flighted (`run_exclusive`) or it will double-
  settle across web replicas.

## Owner / vehicle
All in **luna-service** (billing lives here) — Render deploy, no Luna image
needed. Fix 0 is an operator action runnable today.
