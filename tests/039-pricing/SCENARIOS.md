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
