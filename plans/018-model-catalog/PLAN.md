# 018 — Model catalog: manage, inject, enforce (Luna 007.016 contract)

**Companion to:** `luna/plans/007-provider-base-url/007.016-model-fallback-ui/`.

**No backward compatibility.** Luna 007.016 is merged (`0.13.007`). We replace the
stale model handling with the catalog contract + a small admin surface to **add
models, manage their provider keys, and set the default** that we inject.

## Scope decision (owner, 2026-06-16)

Keep it simple: **in/out + default, head-only.**
- Each model is either **in** the catalog (selectable) or **out**.
- One **default** per purpose (reasoning, summarization) — the head Luna runs.
- **No priority ordering, no multi-entry fallback chain injection.** Luna already
  reads only the chain *head* via `LUNA_PRIMARY_MODEL` / `LUNA_FAST_MODEL`; the
  fallback order stays whatever Luna bakes. No `LUNA_*_CHAIN`, no Luna change.

## Context — what Luna 007.016 consumes (inward only, 007.016 D8)

| Env var | Format | Effect in Luna |
|---|---|---|
| `LUNA_MODEL_CATALOG` | JSON array of entries | **Replaces** Luna's baked catalog wholesale |
| `LUNA_PRIMARY_MODEL` | `provider:model` | Head of the **reasoning** chain |
| `LUNA_FAST_MODEL` | `provider:model` | Head of the **summarization** chain |

Entry shape (`luna/luna/config/schema.py:ModelCatalogEntry`): required `provider`,
`model`, `kinds`; optional `label`, `context_window`, `aliases`, `tier`,
`input_cost`, `output_cost`, `recommended_default`, `deprecated`.

## Current state — five live problems

1. **`LUNA_MODEL_CATALOG` is never injected** (`fly_machines.py:90-95` emits only
   the heads). Tenants run on Luna's *baked* catalog, not ours.
2. **Default model is the brick id.** `DEFAULT_IMAGE_CONFIG.models.primary`/`.fast`
   = `anthropic:claude-sonnet-4-20250514` (`admin_routes.py:244`) — not in Luna's
   catalog → pruned on boot, falls back every turn.
3. **Stale hardcoded `ALL_MODELS`** in `ImageConfigPage.tsx:81` + `MachinesPage.tsx`
   list non-existent ids (`o3`, `o4-mini`, `gpt-4-turbo`, old opus/haiku).
4. **Proxy doesn't enforce the catalog** — passthrough (`gateway_proxy.py`).
5. **We bill failed attempts** (`gateway_proxy.py:110`, `billable=True` regardless
   of status) — the phantom OpenAI rows.

Keys are already gatewayed: machines get a proxy base URL + `lsv1-` token, never a
real key (`provision_env.py:59-67`); the proxy injects the real key from
`gateway_keys`. So the proxy is the unbypassable enforcement point (Phase E).

## Goals

1. Editable **system model catalog** in admin: add / edit / remove a model, toggle
   **in/out**, see/add the provider key, and pick the **default** per purpose.
2. Inject `LUNA_MODEL_CATALOG` (the in models) + the default heads, at provision
   and on live edit.
3. Defaults + all pickers are catalog-sourced — no stale ids, no brick-id.
4. Proxy 404s an off-catalog model on the managed path **before** spending a key;
   aliases resolve; BYOK not gated.
5. Failed attempts are never billable.

## Non-goals

- No pull / no Luna calling us (D8). No `PUT` to each machine. No `LUNA_*_CHAIN`.
- No priority ordering / multi-entry chain editing.
- No per-image / per-agent *catalog* override (the catalog is system-wide). The
  per-machine **default** override already exists (017.1) and stays.
- No embedding switching (Luna read-only, D6) — but embedding entries stay in the
  catalog so memory works through our proxy.

## Approach (phases)

### Phase A — System catalog store (`gateway_models` table)
- New table (sibling to `gateway_services`/`gateway_keys`): `id, provider, model,
  label, context_window, kinds (text[]), aliases (text[]), tier, input_cost,
  output_cost, recommended_default (bool), deprecated (bool), enabled (bool),
  created_at`. `UNIQUE(provider, model)`. `enabled` = in/out.
- Idempotent `CREATE TABLE IF NOT EXISTS` in `main.py` lifespan (same pattern as
  `config_overrides`). **No drops** (data-preservation rule).
- `SEED_MODELS` in `cloud/gateway/model_registry.py`, seeded once if the table is
  empty — identical to Luna's baked `models_catalog.yaml` minus anything our proxy
  can't serve (Anthropic Opus 4.6 / Sonnet 4.5 / Haiku 4.5; OpenAI gpt-4o /
  gpt-4o-mini / text-embedding-3-small / -large), with `aliases` +
  `recommended_default`.

### Phase B — Resolver (`cloud/provisioning/model_catalog.py`, new)
- `system_catalog(db) -> list[dict]` — `enabled` rows in Luna's entry shape.
- `resolve_default_heads(db, image_config, agent_overrides) -> {primary, fast}` —
  per-purpose default: agent override → image `models.primary/fast` → catalog
  `recommended_default` for that kind → first in-catalog model of that kind.
- `validate_head_in_catalog(catalog, head, kind)` — head must be an in-catalog
  model of the right kind; else fall to the catalog default and log.

### Phase C — Fix defaults + kill stale lists
- `DEFAULT_IMAGE_CONFIG.models`: primary → `anthropic:claude-opus-4-6`, fast →
  `anthropic:claude-haiku-4-5-20251001`.
- Delete hardcoded `ALL_MODELS` in both UI pages; source options from the catalog
  the API returns (filtered by kind), showing `label`, grouped by provider,
  `recommended_default` marked, `deprecated` de-emphasized.

### Phase D — Inject catalog + heads
- `workflow.py:_provision_core`: build `LUNA_MODEL_CATALOG` from `system_catalog`;
  resolve + validate the heads; pass both into the spec.
- `fly_machines.py` provision(): `env["LUNA_MODEL_CATALOG"] = json.dumps(catalog)`;
  emit validated `LUNA_PRIMARY_MODEL`/`LUNA_FAST_MODEL`.
- `admin_routes.py:patch_machine_models`: also re-push `LUNA_MODEL_CATALOG` so a
  live machine stays consistent; note "restart to apply".

### Phase E — Proxy enforcement (`gateway_proxy.py`)
- Managed path only; BYOK passthrough unchanged. `service_slug` → provider for
  `anthropic`/`openai` (others not gated).
- Parse `model` from the JSON body; resolve the system catalog (TTL-cached);
  resolve aliases; off-catalog → **404** `{"error":{"type":"not_found",…}}` before
  any upstream call. No body / non-LLM path → skip.

### Phase F — Billing fix (`metering.py` + `gateway_proxy.py`)
- `billable = billable and (status_code is None or status_code < 400)`.

### Phase G — Admin UI: Models management
- New **Models** section (tab in `ServicesPage`, next to keys/services):
  - Catalog table grouped by provider: add / edit / remove; **in/out** toggle;
    fields `provider, model, label, context_window, kinds, aliases, tier,
    input_cost, output_cost, deprecated`.
  - Provider-key column: show `gateway_keys.key_count` for the model's provider +
    deep link to add a key (reuse existing key flow).
  - **Default** selector per purpose (reasoning / summarization): a dropdown over
    the in-catalog models of that kind; writes the main image's
    `models.primary`/`models.fast`. Per-machine override stays in machine settings.
  - Admin API: `GET/POST /api/admin/gateway/models`, `PATCH/DELETE /{id}`.
- Image + machine pickers read the resolved catalog (Phase C).

### Phase H — Tests, backfill, deploy
- Unit: `test_model_catalog.py` (seed → system_catalog; default resolution;
  validate_head); `test_gateway.py` (off-catalog 404 pre-upstream; in-catalog
  passthrough; alias; BYOK bypass; 4xx not billable); `test_admin_models.py`
  (CRUD + audit).
- `dev/backfill_018.py`: push resolved `LUNA_MODEL_CATALOG` + heads to all live
  machines (fixes the brick-id default everywhere).
- `cd cloud/ui && npm run build`; merge to main → Render; verify.

## Data / API contract

- `gateway_models` row → Luna entry via the resolver. System catalog = `enabled`
  rows. Default per purpose = main image `models.primary`/`models.fast` (catalog
  member), per-machine overridable.
- Injected env: `LUNA_MODEL_CATALOG` (JSON), `LUNA_PRIMARY_MODEL`/`LUNA_FAST_MODEL`
  (`provider:model`, ∈ catalog).

## Risks

- **Catalog ≠ provider reality.** Mitigation: keep `SEED_MODELS` + admin catalog in
  lockstep with real ids.
- **Per-request catalog lookup.** Mitigation: TTL cache, invalidate on model write.
- **Env catalog needs a restart.** Acceptable; noted in PATCH response + backfill.
- **Embedding gating.** Catalog includes both embedding entries (Phase A seed).

## Acceptance criteria

- [ ] Admin can add a model, toggle in/out, see/add its provider key, and pick the
      default per purpose; changes persist.
- [ ] A fresh agent has valid `LUNA_MODEL_CATALOG` (parses against Luna's shape) +
      heads that are in-catalog; no path injects an off-catalog head.
- [ ] `DEFAULT_IMAGE_CONFIG` no longer references `claude-sonnet-4-20250514`; no
      `o3`/`o4-mini`/`gpt-4-turbo`/old ids remain in any UI list.
- [ ] Managed proxy request for an off-catalog model → 404 before upstream (no key
      spent); in-catalog passes; alias resolves; BYOK bypasses.
- [ ] A 4xx/failed proxied call is recorded but `billable=False`.
- [ ] Backfill updates every live machine; none left on the brick-id default.
- [ ] Browser walkthrough: edit catalog + default, provision a test agent, confirm
      Luna's Models UI matches what we pushed; a bad-model call falls back (notice)
      without bricking.

## Verification

```bash
cd "<repo>" && source .venv/bin/activate
python -m pytest cloud/tests/test_model_catalog.py cloud/tests/test_gateway.py cloud/tests/test_admin_models.py cloud/tests/test_services_config.py -q
cd cloud/ui && npm run build
# deploy: merge to main → Render auto-deploy; confirm live
python dev/backfill_018.py
# dojo: real browser — Models admin add/edit/toggle/default, provision test agent,
# off-catalog model 404s + Luna fallback notice, usage shows failed call non-billable.
```
