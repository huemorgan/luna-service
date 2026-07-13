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
