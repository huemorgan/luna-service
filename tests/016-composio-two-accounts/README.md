# 016 — Composio two-accounts mode (dojo)

E2E scenarios for the per-image default + per-machine override of
`LUNA_CONNECTORS_ACCOUNTS_MODE`. Browser-driven; you (the LLM) are the test
runner. Each scenario lists steps, what to look for, and pass/fail criteria.

The control plane runs at `https://luna.com.ai` (or the matching
`luna-service.onrender.com` preview if testing pre-deploy). All scenarios
assume you're signed in as an admin (`vaselin@gmail.com`).

## Scenarios

1. `01-image-default-roundtrip.md` — set Composio mode on image config, reload, value persists, new agents inherit
2. `02-per-machine-override.md` — change one machine's dropdown, env var updates within ~30s
3. `03-clear-override.md` — revert agent override, env var follows image default
4. `04-backfill-existing.md` — every production machine now exposes the env var
5. `05-luna-side-pickup.md` — agent UI reflects the mode (only when Luna 007.004 ships; otherwise skip with note)
