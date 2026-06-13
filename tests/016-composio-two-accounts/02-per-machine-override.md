# 02 — Per-machine override

## Goal

Confirm that the Connectors mode dropdown on the Machines page pushes the
new env var to the live Fly machine.

## Steps

1. Navigate to `https://luna.com.ai/admin/machines`.
2. Pick a non-critical agent row (e.g. `luna-vaselin-test-0-08-002`).
3. Note the current image's default Composio mode from the image config page
   (e.g. `both`).
4. In the Machines row, find the **Connectors mode** dropdown. It should
   default to "Use image default ({value})" matching step 3.
5. Change the dropdown to a different value (e.g. `user`).
6. Wait for the UI to confirm (loading spinner → checkmark or row update).
7. While waiting, the Fly API will show the machine briefly cycling. Wait
   ~30s for `state=started` again.
8. Hit `GET /v1/apps/luna-agents/machines/{machine_id}` and read
   `config.env.LUNA_CONNECTORS_ACCOUNTS_MODE`.

## Pass

- Step 5 dropdown change: no error toast.
- Step 6: row visually indicates the override (badge, color, or marker).
- Step 8: `LUNA_CONNECTORS_ACCOUNTS_MODE` equals the override (`user` here).

## Fail

- Dropdown change errors out.
- Machine env stays at the image default.
- Machine fails to recover to `started`.
