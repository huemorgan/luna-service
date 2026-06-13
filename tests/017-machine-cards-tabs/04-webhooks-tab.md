# 04 — Webhooks tab per machine

## Goal

Each card's Webhooks tab shows only that agent's account links + recent
deliveries. The global Relay page is unchanged.

## Steps

1. Expand `roy-billmaster` card (the one with 4 Composio links).
2. Open Webhooks tab.
3. Confirm it shows 4 account links, all belonging to roy-billmaster.
4. Expand a different agent that has 0 links (e.g. `vaselin-test-0-06-001`).
   Confirm the Webhooks tab shows an empty state.
5. From roy-billmaster's Webhooks tab, click "Add link". Confirm the agent
   slug is pre-filled. Enter `ca_test_017` and `gmail`, save.
6. The new link appears in the same card. Navigate to `/admin/relay`, confirm
   the same link appears in the global list.
7. Delete the test link from the global page, refresh the card — the link is
   gone from both views.

## Pass

- Cards with links show only their agent's rows.
- Cards with no links show an empty state, not the global list.
- Add link pre-fills slug and lands in both views.
- Delete works.

## Fail

- A card shows another agent's links.
- Add link form is empty or scoped to the wrong agent.
- New link doesn't propagate.
