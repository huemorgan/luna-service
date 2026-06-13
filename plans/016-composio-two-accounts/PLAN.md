# Plan 016 — Composio Two-Accounts Mode

Surface luna-service support for Luna's 007.004: each tenant machine runs the
connectors plugin with `hosted`, `user`, or `both` Composio accounts. The mode
is **env-only on the machine** (`LUNA_CONNECTORS_ACCOUNTS_MODE`) and we
provision it from a two-level config:

1. **Per-image default** — lives in `LunaImage.image_config.services.composio.accounts_mode`. Picked on the Image Config page.
2. **Per-agent override** — lives in a new `Agent.config_overrides` JSONB column. Picked on the Machines page next to the agent row.

Resolution: agent override → image default → builtin fallback (`"both"` when
the hosted composio key is provisioned, else `"user"`).

Everything else from 007.001 / 013 / 015 stays exactly as today — Luna's
`LUNA_COMPOSIO_API_KEY`, `LUNA_COMPOSIO_BASE_URL`, `LUNA_COMPOSIO_WEBHOOK_SECRET`
are unchanged.

---

## Why two levels (and not more)

Roy explicitly asked for image-level default + machine-level override and
flagged "I feel I'm over-engineering it". So: NO per-account column on
`accounts`, NO new admin page, NO plan tiers. Two places, one env var.

The image config already holds machine / models / plugins / env defaults —
adding a `services.composio` section there is the natural home. The agent
record already lives next to every other per-machine fact. Same shape on both
levels keeps the resolver and audit trail trivial.

---

## Phase A — schema

- `Agent.config_overrides` JSONB nullable. Shape mirrors the `services`
  sub-tree of `image_config`:
  ```json
  { "services": { "composio": { "accounts_mode": "user" } } }
  ```
  NULL = inherit everything from the image.
- Idempotent `ALTER TABLE` in the lifespan (same pattern as the existing
  `image_version`, `cached_metrics_at` migrations in `main.py`).

## Phase B — config resolver

`cloud/provisioning/services_config.py`:

```python
def resolve_composio_accounts_mode(
    image_config: dict | None,
    agent_overrides: dict | None,
    hosted_key_provisioned: bool,
) -> str:
    # agent override wins; then image default; then builtin
    for src in (agent_overrides, image_config):
        try:
            v = (src or {}).get("services", {}).get("composio", {}).get("accounts_mode")
        except AttributeError:
            v = None
        if v in ("hosted", "user", "both"):
            return v
    return "both" if hosted_key_provisioned else "user"
```

`hosted_key_provisioned` is derived from `GatewayService` row for `composio`
(`enabled=True AND provision_by_default=True AND key_count > 0`).

`build_gateway_env` (already loops the registry) gains a single
`LUNA_CONNECTORS_ACCOUNTS_MODE` line at the end. The function gets two new
arguments: `image_config` and `agent_overrides`. `_provision_core` passes both.

## Phase C — image config

- `DEFAULT_IMAGE_CONFIG` (admin_routes.py) grows:
  ```python
  "services": {"composio": {"accounts_mode": "both"}}
  ```
- `ImageConfigUpdate` pydantic model gains a `services: dict | None` field.
- `ImageConfigPage.tsx` gets a new `SectionCard` ("Services") with a single
  dropdown for `services.composio.accounts_mode` (hosted / user / both).
  Auto-saves through the existing PUT path.

## Phase D — per-agent override

- `GET /api/admin/machines` returns `config_overrides` and a resolved
  `accounts_mode` for display.
- `PATCH /api/admin/machines/{machine_id}/services-config` sets
  `agent.config_overrides.services.composio.accounts_mode`, then calls
  `update_machine_env({"LUNA_CONNECTORS_ACCOUNTS_MODE": resolved})` on the
  live machine. Audit-logged. Setting the value to `null` clears the override
  (reverts to image default).
- `MachinesPage.tsx`: each row gets a small "Connectors mode" dropdown with
  the four options: **Use image default (X)**, hosted, user, both. Changing
  triggers the PATCH and updates the table.

## Phase E — backfill

Existing 8 machines don't have `LUNA_CONNECTORS_ACCOUNTS_MODE` at all. A
one-time script `dev/backfill_016.py` walks every live agent, resolves the
mode from the current image config (defaults to `both` since the composio
hosted key is provisioned), and pushes the env var via `update_machine_env`.
Run once after deploy.

## Phase F — UI rebuild + deploy + tests

- `cd cloud/ui && npm run build` (then commit `dist/`).
- Unit tests in `cloud/tests/test_services_config.py`:
  - resolver returns agent override over image default
  - resolver falls back to builtin when both unset
  - invalid values ignored (resolver returns next-level value)
  - `build_gateway_env` includes `LUNA_CONNECTORS_ACCOUNTS_MODE`
- Dojo scenarios in `tests/016-composio-two-accounts/`:
  1. **Image default round-trip** — admin sets Composio mode to `hosted` on
     the image config page; reload, value persists; new agent provisioned
     gets `LUNA_CONNECTORS_ACCOUNTS_MODE=hosted` in its env.
  2. **Per-machine override** — pick an existing machine, change its
     dropdown to `user`; the live machine env updates within ~30s and the
     UI shows the override badge.
  3. **Clear override** — set the agent dropdown back to "Use image default";
     env reverts to whatever the image says.
  4. **Backfill** — verify all 8 production machines now expose
     `LUNA_CONNECTORS_ACCOUNTS_MODE` (via Fly machines API exec).

## Phase G — live walkthrough

Browser into the admin → change the connectors mode on the
`luna-vaselin-test-0-08-002` row to `user` → verify Fly env via API → reload
the Luna agent in another tab and confirm the connectors UI reflects the new
mode (this depends on Luna's 007.004 ship — if not yet live, we verify only
the env var landed).

## Decisions

| Topic | Decision |
|---|---|
| Storage | Image default + per-agent override (two levels). No per-account column. |
| Builtin default | `both` if the hosted composio service has a key in the pool; else `user`. Matches Luna's spec. |
| UI placement | Services section on ImageConfigPage; per-row dropdown on MachinesPage. No new pages. |
| Existing-machine rollout | `dev/backfill_016.py` after deploy. Same `update_machine_env` path as plan 014. |
| Same-app-on-both collision | UI warning only (Luna's side). luna-service doesn't filter. |
| Future services | The `services.{slug}` key shape is reusable — adding the next service is a one-line dropdown on each page. |

## Definition of done

- DB has `agents.config_overrides` column.
- `_provision_core` injects `LUNA_CONNECTORS_ACCOUNTS_MODE` for every new
  machine.
- Image Config page shows a Composio mode dropdown that round-trips.
- Machines page shows a Connectors mode dropdown per row that pushes the env
  var to the live machine.
- All 8 existing production machines carry the env var.
- Unit tests + dojo scenarios pass.
- Committed and pushed.
