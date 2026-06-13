# 03 — Settings: Connectors plugin

## Goal

The Settings tab explains the three Composio modes and the "Inherit" option,
and writing each option pushes the env var to the live machine.

## Steps

1. Expand a non-critical machine card; open Settings.
2. Read the Connectors plugin section. Confirm all four radios exist with
   explanations:
   - Inherit image default ({mode})
   - Hosted only
   - User-provided only
   - Both
3. Select "User-provided only". Wait for the Saving / Saved indicator.
4. Confirm the card header now shows an "override" badge.
5. Verify Fly machine env: `GET /v1/apps/luna-agents/machines/{id}` →
   `config.env.LUNA_CONNECTORS_ACCOUNTS_MODE` equals `user`.
6. Select "Inherit image default ({mode})". Wait for it to apply.
7. Confirm the override badge is gone and the Fly env reflects the image
   default again.

## Pass

- All four radios present, with copy as in PLAN.md.
- Selecting writes via `PATCH /api/admin/machines/{id}/services/composio`
  with `accounts_mode` = the chosen value, or `null` for Inherit.
- Fly env updates to match within ~30s.
- Override badge tracks the state.

## Fail

- Any radio missing or unlabeled.
- PATCH errors out.
- Fly env doesn't track the UI.
