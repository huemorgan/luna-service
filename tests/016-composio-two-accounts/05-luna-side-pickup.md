# 05 — Luna picks up the mode (deferred dependency)

## Goal

Once Luna 007.004 lands, confirm the connectors plugin uses our env var to
decide which tabs to render.

## Note

This scenario is BLOCKED until Luna ships 007.004. The OSS side is in
progress per the 007.004 plan & FOR-LUNA-SERVICE.md handoff in the luna/
submodule. Until then, the connectors UI in agent space shows today's
single-account view regardless of our env var — that's expected.

## Steps (run after Luna 007.004 ships)

1. Pick an agent. Set its `LUNA_CONNECTORS_ACCOUNTS_MODE` to `hosted` via
   the Machines page (scenario 02).
2. Open the agent's Settings → Connectors page.
3. Confirm: ONE tab visible ("Included with Luna Cloud"), no key entry.
4. Switch the override to `user`. Reload agent.
5. Confirm: ONE tab visible ("Your Composio account"), key entry visible.
6. Switch to `both`. Confirm: TWO tabs.

## Pass

- Tab count matches the mode.
- No key entry surface in `hosted` tab; key entry visible in `user` tab.

## Fail

- Tab count doesn't match.
- Key entry visible where it shouldn't be.
