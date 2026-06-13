# 01 — Image default round-trip

## Goal

Verify that setting `services.composio.accounts_mode` on an image's config
page persists across reloads and lands on newly-provisioned machines.

## Steps

1. Navigate to `https://luna.com.ai/admin/images`.
2. Click the main image row to enter its Image Config page.
3. Scroll to the new **Services** section card.
4. Find the **Composio · Connectors mode** dropdown. Note the current value.
5. Change it to a different value (e.g. from `both` → `hosted`).
6. Wait for the "Saved" badge to appear.
7. Hard-reload the page (Cmd-Shift-R).
8. Confirm the dropdown still shows the new value.
9. Provision a fresh test agent through the admin Machines page (or use a
   normal user flow if onboarding handles it). Wait for it to reach
   `started` state.
10. Hit the Fly API: `GET /v1/apps/luna-agents/machines/{machine_id}` and
    look for `config.env.LUNA_CONNECTORS_ACCOUNTS_MODE`.

## Pass

- Step 6: the "Saved" indicator flashes.
- Step 8: the dropdown shows the changed value after reload.
- Step 10: `LUNA_CONNECTORS_ACCOUNTS_MODE` equals the value picked in step 5.

## Fail

- Dropdown doesn't appear at all.
- Value doesn't persist after reload.
- New machine env doesn't have the variable or has the old value.
