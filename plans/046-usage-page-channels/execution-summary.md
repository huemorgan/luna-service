# Plan 046 execution summary

Date: 2026-07-17
Branch: `046-usage-page-channels`
Deploy state: see "Deploy" below
Commit state: committed on branch

## What was accomplished

### Backend — per-channel attribution

- Added a nullable `channel` column to `billable_events`
  (`cloud/billing/models.py`) plus index `ix_be_account_channel_event_at`
  for `(account_id, channel, event_at)`. Additive migration
  `cloud/alembic/versions/0010_billable_event_channel.py`.
- Gateway ingests the `x-luna-channel` header
  (`cloud/gateway/enforcement.py`): validated against
  `{web, whatsapp, telegram, scheduler, api}`, coerced to `NULL` when
  absent or unrecognized, and persisted on both the would-block and the
  normal `BillableEvent` paths via `BillingContext.channel`.
- New aggregation endpoint `GET /api/billing/usage/channels`
  (`cloud/api/billing_routes.py`): groups `RatedCharge` credits by channel
  and day into four sections (`web`, `scheduler`, `whatsapp`, `telegram`),
  returns a shared `y_max` so every chart uses one y-scale, a 28-day
  `trend` and `total` per section, and per-trigger breakdown for scheduler
  (by `job_id` / `root_action_id`). Legacy `channel = NULL` and `api` fold
  into `web`. Accepts optional `agent_id` to filter to one Luna.

### Frontend — Usage / Billing split + Dashboard status

- Split the old tabbed page into two: new `billing/UsagePage.tsx`
  (`/dashboard/usage`) and a slimmed `billing/BillingPage.tsx`. Removed the
  `TABS` bar and all `?tab=` handling. Header shows **Usage** and
  **Billing** as separate links on both pages and the Dashboard.
- `UsagePage`: top Luna filter pulldown (reads `?agent=`), range control,
  and four stacked 28-day bar charts (Chat/web, Scheduled triggers,
  WhatsApp, Telegram) all sharing the endpoint's `y_max`. Scheduled section
  is expandable to per-trigger charts. Per-Luna limit editor retained.
- Luna cards (`Dashboard.tsx` `AgentCard`) and `SpendCard.tsx` gained a
  **Usage** deep-link → `/dashboard/usage?agent={id}`.
- **Payment status kept (user correction):** the account/payment status
  breakdown is NOT on Billing. New shared `billing/StatusBreakdown.tsx`
  renders payment-status banners, balance stats, credit sources, always-on
  hosting, and credit lots. It lives on the **Dashboard** behind a
  collapsible "Account & payment status" toggle (open to see the
  breakdown). Billing = payment banners + packages + statement + a one-line
  pointer to the dashboard status panel.
- New API types (`billing/api.ts`): `ChannelTrendPoint`, `ChannelTrigger`,
  `ChannelSection`, `ChannelUsage`. Route `/dashboard/usage` added in
  `App.tsx`.

## Verification

- Customer billing API tests: 21 passed
  (`cloud/tests/test_billing_customer_api.py`), including
  `test_usage_channels_sections_and_ymax` (sections, shared `y_max`,
  per-trigger split, legacy NULL fold) and `test_usage_channels_agent_filter`.
- Channel/gateway/enforcement focused suite: 118 passed.
- Frontend production build: passed. Edited-file lint: clean.
- Dojo E2E (headless Playwright on real Postgres,
  `tests/046-usage-page-channels/dojo_usage_channels.py`): S1–S6 + S5b all
  PASS with screenshots in `results/2026-07-17-local/`:
  - S1 Usage/Billing separate, no tabs/Status tab.
  - S2 four sections share one y-scale (chat peak 100% vs telegram ~2%).
  - S3 scheduler lists + expands two triggers.
  - S4 Luna filter + card deep-link pre-filter.
  - S5 Billing = packages + statement only, no status breakdown.
  - S5b Dashboard "Account & payment status" toggle reveals balance +
    credit sources.
  - S6 endpoint shape, totals, `y_max`, per-trigger, `agent_id` filter.

## What we discovered

- **`root_action_type` is effectively NULL in production.** Luna's runtime
  emits `chat_turn` / `task_run`, which the gateway's allow-list does not
  recognize, so it stores `NULL`. Keying the Usage sections on the new
  `channel` dimension (origin of the interaction) rather than
  `root_action_type` is therefore both more correct and more robust. The
  companion Luna change (emit `x-luna-channel` + fix `root_action_type`) is
  tracked as a proposal in `luna/plans/`.
- Until Luna sends `x-luna-channel`, all existing rows and new web traffic
  fold into the **Chat (web)** section; WhatsApp/Telegram/Scheduler sections
  populate as soon as those channels tag their calls. The UI degrades
  gracefully (empty sections still render an axis).
- Playwright `inner_text()` honors CSS `text-transform: uppercase`, so DOM
  assertions on section titles must compare case-insensitively.

## Deploy

- Migration `0010` is additive/nullable and runs automatically on deploy
  (`python -m cloud.db.migrate` in `cloud/Dockerfile` CMD, before uvicorn).
- Render builds the UI inside the Docker image; no committed `dist` needed.
