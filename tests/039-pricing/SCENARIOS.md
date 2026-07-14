# 039/002 — Admin pricing UI dojo scenarios

Environment: local app (`uvicorn cloud.main:app --port 8100`) against a dedicated
Postgres database (`dojo039` on the docker PG, migrated to head 0003), billing
worker on, relay forwarder and reconciler off. Admin session minted directly
(signed `luna_session` cookie) — Google OAuth is not exercised here.

Run: `python3 tests/039-pricing/dojo_admin_ui.py` (Playwright headless chromium;
`DOJO_USER_ID` / `DOJO_ACCOUNT_ID` env). Evidence: screenshots + assertions in
`results/<date>-local/`. No Playwright MCP browser was available this session,
so this scripted run is the dojo substitute.

## Scenarios

1. **Sidebar navigation** — the admin sidebar shows a collapsible Pricing group
   with Overview, Versions, LLM & services, Credit buckets.
2. **Overview** — shows the seeded default version v1 (published), credit
   liability / customer debt / assigned-accounts / dead-jobs stats, and no red
   attention banner on a healthy system.
3. **Clone to draft** — Versions page lists v1 (published); Clone creates a v2
   draft.
4. **Draft edit + diff** — v2 detail: raw JSON editor accepts a change
   (`trial.gift_credits` 1800 → 2000), Save reports "Draft saved and
   validated.", and Diff vs parent shows exactly that path.
5. **Server-side validation surfaces in UI** — setting `trial.gift_credits`
   to -5 and saving shows the server's validation message; the draft is
   unchanged.
6. **Reason-gated publish** — Publish is disabled with an empty reason; with a
   reason it publishes and the version becomes immutable (editor read-only).
7. **LLM & services page** — tier lists, LLM credit constants, SKU catalog and
   provider-cost versions render from the newest published version, read-only
   with a "Clone to draft to edit" affordance.
8. **Credit buckets page** — trial gift, migration gift and product table
   (prices, paid/bonus credits, Stripe placeholder column) render read-only.
9. **Rollout end-to-end** — New Rollout (v2, new accounts, reason) schedules a
   durable job; the billing outbox worker picks it up within its 5 s poll and
   the rollout reaches `completed`; Overview then reports v2 as the default
   version. This proves UI → API → billing_outbox → worker → default change.

## CSRF note

Cross-origin mutation rejection (Origin/Referer vs base_url) is covered by
coded tests in `cloud/tests/test_billing_admin_api.py` — it needs forged
headers, which a real browser page can't produce, so it is intentionally not a
browser scenario.

---

# 039/004 — Gateway metering & enforcement dojo scenarios

Environment: dedicated Postgres database (`dojo039gw` on the docker PG,
migrated to head), real uvicorn app booted once per billing mode
(`CLOUD_BILLING_MODE` = observe / shadow / enforce, port 8103), billing outbox
worker on (real 5 s poll settles holds live), relay forwarder and reconciler
off. A local mock Anthropic upstream (port 8109) returns real JSON and SSE
`/v1/messages` responses with usage, so the full network path — client → luna
gateway → upstream — is exercised on the wire. Two funded states: `funded`
(100 credits) and `broke` (0 credits), each with its own agent + gateway token.

Run: `python3 tests/039-pricing/dojo_gateway_billing.py`. Evidence:
`results/<date>-local/REPORT-gateway.txt` + per-mode app logs. No browser UI
exists for this phase (proxy plane only), so the dojo is live-network + SQL
assertions rather than Playwright.

## Scenarios

0. **Scratch DB** — dropped/recreated `dojo039gw`, `python -m cloud.db.migrate`
   to head, seeded services/models/billing v1 + accounts/agents/tokens.
1. **Observe mode** — broke account's call passes through; a BillableEvent and
   a RatedCharge (`charge_status=observed`) are recorded; wallet untouched, no
   hold created.
2. **Shadow mode** — broke account passes through, but the real authorize
   decision runs inside a rolled-back savepoint and records
   `would_block=credits_exhausted` in the rule snapshot; zero customer effect.
3. **Enforce, empty wallet** — 402 `credits_exhausted` before any provider
   contact (upstream saw no request).
4. **Enforce, JSON happy path** — call held pre-flight, upstream JSON usage
   (1000 in / 500 out on the top tier) rated to 4 credits, the live outbox
   worker settled the hold: balance 100 → 96.
5. **Enforce, SSE** — `stream:true` response parsed on the wire in 40-byte
   chunks (usage split across frames, max-merged); alias `opus` canonicalized
   to `claude-opus-4-6` in the billing rows.
6. **Enforce, routing** — unknown route → 402 `sku_unpriced` (deny by
   default); a free route passes even for the broke account.
7. **Enforce, attribution** — `x-luna-call-id` / `x-luna-context` stripped
   before the upstream (mock upstream asserts absence); correlation id
   recorded namespaced `{agent_id}:{tenant_id}`.
8. **Terminal holds** — after a settle-poll window every hold is terminal
   (`settled`), none stuck `open`, none `needs_reconciliation`.

---

# 039/005 — Grants, hosting lifecycle & limits dojo scenarios

Environment: dedicated Postgres database (`dojo039host` on the docker PG,
migrated to head 0004), real uvicorn app booted per billing mode (enforce,
then observe; port 8104), billing outbox worker AND maintenance loop on (the
loop's immediate boot tick + 60 s cadence drives renewals live), relay
forwarder and reconciler off. `CLOUD_RUNTIME=fly-machines` with a
deliberately invalid `FLY_API_TOKEN` — every Fly call gets a real 401 on the
wire, so provisioning/suspend failure paths are exercised without touching
real infrastructure. Account A is created through the REAL signup transaction
(`_upsert_user_and_account`, in-process); B (broke, past-due period),
E (funded, anchored on the 31st, past-due period) and C (funded, current
period) are seeded directly.

Run: `python3 tests/039-pricing/dojo_hosting_lifecycle.py`. Evidence:
`results/<date>-local/REPORT-hosting.txt` + `app-hosting-*.log`.

## Scenarios

0. **Migration to head on PG** — scratch DB reaches head; 0004's
   `agents.deleted_at` tombstone column present.
1. **Trial gift exactly once** — real signup path grants 1800 credits
   (`source_key trial:{account_id}`); a second login of the same user does
   not duplicate the grant.
2. **Enforce create** — POST /api/agents → 201 with a `pending` hosting
   period priced 999, an open 999-credit hold (`hosting:{period_id}`), a
   durable `hostprov` outbox job, and trial per-Luna limits 75/day, 800/month.
3. **Trial cap** — second create on the trial account → 402
   `active_luna_limit`; no rows written.
4. **Durable provisioning failure** — the worker's provision attempt fails
   against Fly (401), the job records attempts/last_error and stays queued,
   the hold stays `open` (never silently released); POST /retry requeues the
   job (attempts reset) and returns 200.
5. **Live renewal with anchor clamp** — E's period (May 31 → Jun 30, anchor
   day 31) is past due at boot; the maintenance loop renews it seamlessly
   (new period Jun 30 → Jul 31, anchor restored from the clamped 30th) and
   charges exactly 999: balance 1800 → 801.
6. **Unpayable renewal** — broke B's past-due period flips to `payment_due`
   with a durable `hostsusp` suspend job; POST /start → 402
   `hosting_payment_due`.
7. **Admin gift** — POST /api/admin/pricing/gifts without a reason → 400 and
   no money movement; with a reason → grant created (default expiry from
   `gift_default_days`) and a `pricing.gift.create` audit row.
8. **Recovery via start** — after the 1200-credit gift, POST /start charges
   a fresh month (999), clears `payment_due`, opens a new active period:
   balance 1200 → 201. The runtime start itself fails (bogus Fly token) —
   the billing commit survives it.
9. **Soft delete** — DELETE tombstones the agent (`deleted_at`, stopped),
   ends its period, keeps every billing row (grants intact), runs the
   durable teardown job to success, and hides the agent from list/get.
10. **Observe mode** — create succeeds despite the trial cap (logged only),
    the lifecycle period row is written, and zero holds exist: no money
    movement outside enforce.

## Notes

- The invalid-token trick must be present-but-bogus, not absent:
  `start_agent` constructs the runtime outside its try/except, so a missing
  `FLY_API_TOKEN` would 500 and roll back the recovery charge (scenario 8).
- E's seed dates are chosen so exactly ONE renewal lands in the future
  (Jun 30 → Jul 31); older dates would chain a renewal per 60 s sweep until
  the balance ran dry and flip the account to `payment_due` mid-run.

# 039/008 — Customer billing UI dojo scenarios

Environment: dedicated Postgres database (`dojo039bill` on the docker PG,
migrated to head), one real uvicorn app in enforce mode on port 8105 with
`CLOUD_BASE_URL` pointed at the dojo port (the CSRF same-origin guard
compares the browser's Origin against it), billing outbox worker on,
forwarder/reconciler off, `FLY_API_TOKEN` present-but-bogus. The account is
created through the REAL signup transaction (trial gift 1800), then one
running Luna ("Mika") is seeded with an active hosting period, per-Luna
limits 75/800/80%, and a week of varied usage: 7 rated calls across
chat / playbook (with a composio plugin child) / scheduled / background,
including a 2-attempt chat call that must be counted once. Matching
`ledger.charge` postings burn the trial gift down to 1,678. Playwright
headless chromium 1440×960 with `reduced_motion="reduce"` (the marketing
site reveals sections on scroll; screenshots would capture blanks otherwise).

Run: `python3 tests/039-pricing/dojo_billing_ui.py`. Evidence:
`results/<date>-local/REPORT-billing-ui.txt` + screenshots 10–17 +
`app-billing-ui.log`.

## Scenarios

1. **Marketing /pricing from the API** — trial card ($0, 1,800 credits,
   28 days, 75/day, 1 active Luna), Hobby/Pro/Power from
   `/api/public/pricing`, top-ups card and always-on hosting card;
   no "degrade gracefully" copy anywhere.
2. **Yearly toggle** — prices become per-month billed-yearly
   ($100/mo billed yearly for Pro) and yearly gift credits appear
   ("+10,000 gift credits each year").
3. **Dashboard nav** — header Billing link routes to /dashboard/billing.
4. **Billing overview** — trial banner (days left, active-Luna cap),
   balance 1,678 cr, in-flight 0, debt 0, next expiry date; three package
   cards render disabled "Coming soon" buttons (payments_enabled false
   until 007).
5. **Credit lots** — gift lot 1,678 / 1,800 remaining, expiry, status
   active, burn order #1, cheapest-first note.
6. **Usage** — 122 cr in 28d, today/month stats, est. days left, trend
   bars, per-Luna row 49 / 75 cr daily with progress + 122 / 800 monthly.
7. **Breakdown pivots** — Luna / Service / Plugin / Action type / Model /
   Action buttons re-query; model shows claude-sonnet-5, plugin shows
   whatsapp 4 cr.
8. **Recent actions** — playbook run groups its composio plugin child
   (22 + 4 = 26 cr), expanding reveals the child rows; the 2-attempt chat
   shows 18 cr exactly once.
9. **CSV export** — `/api/billing/usage/actions.csv` honours the session
   cookie, 6 data rows, frozen header `time,luna,action,service,status,credits`.
10. **Statement** — trial gift +1,800 row and a correct per-row running
    balance ending at 1,678.
11. **Limit editor** — owner edits daily 75→100 through the same-origin
    PUT; the UI re-renders 49 / 100 cr and the DB row agrees.
12. **AgentDetail Spend card** — real daily/monthly usage with "of 800 cr
    limit" hint and hosting state (active · 999 cr until date).

## Notes

- `ledger.charge` must not be given a `now` older than the grant's
  `effective_at`: burnability filters `effective_at <= now`, so a stale
  `now` silently sends the charge to DEBT while the wallet balance still
  moves — the page looks right except lots never shrink.
- Inside `with sync_playwright()` an asyncio loop is already running on the
  thread; `asyncio.run()` for DB assertions must happen on a fresh thread.
- The customer API never sends margins, micro-USD, tiers, contexts, SKUs or
  vendor costs; the API tests assert those tokens are absent from payloads.
