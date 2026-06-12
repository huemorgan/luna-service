# 05 — Admin visibility

Operators must be able to see what flowed through the relay and fix
mappings by hand.

## Steps

1. Log into the control plane UI as the admin user, open the admin area,
   find the Webhook Relay section.
2. Deliveries table shows the rows produced by scenarios 01-04 with:
   status, agent (or "—" for unroutable), attempts, timestamps. Statuses
   are visually distinguishable (delivered / pending / unroutable / dead).
3. Links table shows existing connected-account → agent mappings.
4. Add a link via the UI (or admin API if the UI is API-only this phase):
   connected_account_id `ca_manual_test` → some agent; it appears in the
   list. Delete it; it disappears.
5. Non-admin user hitting `GET /api/admin/relay/deliveries` gets 403.

## Pass

- All of the above observable in the browser with screenshots; admin-only
  enforcement holds.

## Fail

- Missing/empty tables despite prior scenarios, CRUD not working, or
  non-admin access succeeding.
