# Plan 017 — Per-machine admin: expandable cards with tabs

Replace the flat Machines table with image-style expandable cards. Per-machine
state moves under each machine, organized in tabs (Overview / Settings /
Webhooks). The connectors-mode dropdown moves into Settings with a proper
"Connectors plugin (Composio)" section that explains what each option means.

## Why

Today everything machine-specific lives in two places:
- a wide table column on the Machines page (just the connectors-mode dropdown)
- the Webhook Relay page (account links + deliveries for *all* machines)

Roy wants per-machine config grouped under each machine, like the Images page.

## Out of scope

- Backend changes — the existing endpoints already return everything we need.
- Cross-machine views (the Webhook Relay page stays as-is for the global view).
- New machine config beyond what's already there (no new env-var editor yet).

## Phase A — UI skeleton

1. New `MachineCard` component in `MachinesPage.tsx`:
   - Header (always visible): state dot + agent_name + agent_slug pill, region,
     version, machine_id short hash, override badge if any, chevron.
   - Click anywhere on the header toggles expand.
   - Border highlight (moon) when `override` is set, mirroring the "main" image highlight.
2. Inside expanded body, a tab strip: **Overview · Settings · Webhooks**.
3. Default tab is Overview.

## Phase B — Overview tab

- Move the existing "Update to main image" button here.
- Add a small key-value grid: image version, fly state, region, machine_id,
  fly image tag, fly created_at.
- This is everything we already show on the row, just relocated.

## Phase C — Settings tab

One section card:

> **Connectors plugin (Composio)**
>
> Controls how the connectors plugin lets this Luna talk to Composio. The plugin
> exposes one tab per allowed mode in the agent's Settings → Connectors page.
>
> ○ Inherit image default — *current default: {mode}*
> ○ **Hosted only** — Luna uses our shared Composio key. The user sees one
>   "Included with Luna Cloud" tab and never enters their own key.
> ○ **User-provided only** — The user must paste their own Composio API key.
>   No hosted tab is shown. Useful for BYO-account customers.
> ○ **Both** — Both tabs visible. The user can choose between hosted and their
>   own key.

Implementation:
- Radio buttons, single column, with description under each.
- Same PATCH endpoint we already have: `/api/admin/machines/{id}/services/composio`
- "Inherit" = sends `accounts_mode: null`.

## Phase D — Webhooks tab

Per-agent slices of the existing relay data:

- Fetch `/api/admin/relay/links` and `/api/admin/relay/deliveries` once at the
  page level (so all cards share one fetch).
- In each card's Webhooks tab, filter both lists by `agent_slug === card.agent_slug`.
- Show:
  - **Account links** table (connected_account_id, app, source, last seen,
    delete button) — same columns as RelayPage, just filtered.
  - **Recent deliveries** for this agent (last 10), with status/timestamp.
- "Add link" button is scoped to this agent (pre-fills `agent_slug`).

Webhook Relay page is unchanged — still the global view.

## Phase E — Build + deploy + verify

- `cd cloud/ui && npm run build` (must pass)
- Lint: nothing new beyond what the file already has
- Merge to main → Render auto-deploys
- Browser walkthrough on production:
  1. Open `/admin/machines`, confirm each row is now a card
  2. Expand one, tab through Overview / Settings / Webhooks
  3. Change Settings mode → confirm row badge updates → verify Fly machine env
  4. Add a link on Webhooks tab → confirm it appears in the same card and on
     the global Relay page

## Definition of done

- Machines page renders cards, not table rows.
- Each card has 3 working tabs.
- Settings → Connectors plugin radio writes via PATCH and reflects override state.
- Webhooks tab shows only this agent's links + deliveries.
- Render deploy live; verified in browser.
