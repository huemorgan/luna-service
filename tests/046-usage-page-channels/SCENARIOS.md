# 046 — Usage page + per-channel attribution — dojo scenarios

LLM-run in a real browser (Playwright). Harness: `dojo_usage_channels.py`
seeds a scratch Postgres DB with a customer, two Lunas, and 28 days of
`billable_events` tagged with `channel` (web / whatsapp / telegram /
scheduler), then drives the built SPA. Screenshots in `results/`.

## S1 — Top bar: Usage and Billing are separate sections

- From `/dashboard`, the header shows **Usage** and **Billing** as two
  distinct links.
- Click **Usage** → lands on `/dashboard/usage`.
- Click **Billing** → lands on `/dashboard/billing`.
- PASS: both links exist and route correctly; there is **no tab bar** and
  **no "Status" tab** anywhere on either page.

## S2 — Usage page: four channel sections, shared y-scale

- On `/dashboard/usage` (All Lunas) there are exactly four sections in
  order: **Chat**, **Scheduled triggers**, **WhatsApp**, **Telegram**.
- Each renders a 28-day bar chart with a y-axis in credits.
- Seed makes Chat the tallest (max ~200/day) and Telegram small (max
  ~10/day). PASS: the Telegram bars render visibly short (not
  full-height) — i.e. all four charts share one y-max. Verify by reading
  the rendered bar heights / inline styles.

## S3 — Scheduled triggers expand per-trigger

- The Scheduled section shows one accumulated bar chart + a list of
  triggers.
- Expand a trigger → its own 28-day bar chart + total credits appear.
- PASS: at least two distinct triggers listed, each expandable with its
  own chart.

## S4 — Per-Luna filter + card deep-link

- Usage page top has a Luna pulldown (All Lunas + each Luna name).
- Selecting a Luna updates all four charts to that Luna's credits only
  (totals change).
- From `/dashboard`, each Luna card has a **Usage** button → navigates to
  `/dashboard/usage?agent={id}` with the pulldown pre-set to that Luna.
- PASS: filter changes numbers; card button deep-links pre-filtered.

## S5 — Billing page: no usage content, no tabs

- `/dashboard/billing` shows balance summary + packages + statement.
- PASS: no "Where credits went", no "Recent actions", no tab bar, no
  Status tab. Balance/sources/hosting/lots info still present (folded in).

## S6 — Backend: /usage/channels (API-level, via httpx)

- `GET /api/billing/usage/channels?range=28d` returns `sections` with
  `web/scheduler/whatsapp/telegram`, a shared `y_max`, per-section
  `trend` (28 points) and `total`, and `scheduler.triggers[]`.
- `?agent_id=` filters to one Luna.
- Legacy rows with `channel = NULL` fold into `web`.
- PASS: shape + filtering + shared y_max correct.
