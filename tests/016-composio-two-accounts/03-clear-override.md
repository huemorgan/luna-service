# 03 — Clear per-agent override

## Goal

Confirm that picking "Use image default" reverts to whatever the image
default currently says.

## Steps

1. Start from the state at the end of scenario 02 (the row has an override).
2. Open the Connectors mode dropdown.
3. Pick **Use image default**.
4. Wait for the row to settle.
5. Hit the Fly API and read `config.env.LUNA_CONNECTORS_ACCOUNTS_MODE`.

## Pass

- Dropdown reverts to "Use image default ({value})".
- Override badge / marker is gone.
- Env var equals the image default (the value from scenario 01 step 3).

## Fail

- Env var still equals the previous override value.
- UI keeps showing the override after clearing.
