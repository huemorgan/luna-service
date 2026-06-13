# 04 — Backfill existing production machines

## Goal

Every existing tenant machine running before this change now carries
`LUNA_CONNECTORS_ACCOUNTS_MODE`.

## Steps

1. Pre-deploy: SSH-exec `env | grep LUNA_CONNECTORS_ACCOUNTS_MODE` on a
   sample machine — expect empty.
2. Deploy luna-service with the 016 changes.
3. Run `python dev/backfill_016.py` from a shell with `FLY_API_TOKEN` set.
4. Confirm the script reports `updated N` for each of the 8 known machines.
5. Hit each machine's exec endpoint with `env | grep LUNA_CONNECTORS`.

## Pass

- Step 1: empty before deploy.
- Step 4: 8 updates, 0 errors.
- Step 5: every machine reports `LUNA_CONNECTORS_ACCOUNTS_MODE=...`
  (default `both`, since the hosted composio key is provisioned).

## Fail

- Script errors out for any machine.
- Any machine still missing the env var afterwards.
