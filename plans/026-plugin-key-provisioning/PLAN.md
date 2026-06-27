# Plan 026 — Plugin key provisioning via the gateway

## Goal

Let an admin attach **our** keys to plugins so they work the instant they land on a
tenant machine — without the real key ever touching the machine or the agent.

Two lists in the admin:

1. **Default plugin set** (baked into every new/updated image) — each plugin can be
   given a default key picked from our gateway key pool. Baked plugins start
   connected, no user action.
2. **Supported plugins** (a parallel catalog, *not* baked) — same key wiring, but
   the env is only provisioned when a user chooses to install the plugin. Each entry
   carries a smart, pre-filled key suggestion that fits the plugin.

Reuse the credential gateway (plan 013) — it is exactly the "don't compromise the
key" architecture: the machine gets a proxy URL + a per-tenant `lsv1-` token; the
gateway swaps that token for a real pool key and forwards upstream. The plugin never
sees the key.

## Relationship to 026.1 (read first)

026 is the **admin / control-plane half**: the plugin↔key catalog, bindings, the two
lists, the suggester, and the install hook. **026.1 owns the machine-facing decisions**
and 026 defers to them:

- Provisioning injects **one** `LUNA_GATEWAY_URL` + device token — **not** per-service
  env vars.
- Plugins consume keys via **`ctx.vault.connect(slug)`** (returns a real or virtual
  `Connection`) — **not** by reading `LUNA_<SLUG>_API_KEY`.
- Bindings here decide what the 026.1 **inventory discovery** endpoint marks
  `provisioned`, which is what surfaces virtual keys in the vault. No local gateway table.

---

## How the gateway already works (recap — the thing we extend)

- `GatewayService` = one upstream (slug, `upstream_url`, `auth_style`, env var names,
  `enabled`, `provision_by_default`). Arbitrary services already supported.
- `GatewayKey` = encrypted key in a pool, scoped `global` or `agent:<id>`, priority +
  cooldown + fallback. Write-only via admin API.
- `build_gateway_env(agent)` emits, for every service with
  `provision_by_default=True`: `LUNA_<SLUG>_BASE_URL = {base}/proxy/<slug>` and
  `LUNA_<SLUG>_API_KEY = <tenant token>` (+ SDK-standard aliases).
- `/proxy/{slug}/{path}` (`gateway_proxy.py`): tenant token → real key from the pool,
  forwards upstream, meters usage. Real key stays server-side. BYOK passes through.
- Plugin side: `resolve_credential(name, env_var, vault)` = **vault first, env var
  fallback**. `CredentialSlot(slug, credential_name, env_key_var, owner)` already
  declares the env var name a plugin reads.

So the missing pieces are only: (a) a plugin↔service binding, (b) provisioning driven
by *plugin membership* instead of one global flag, (c) admin UI for both lists, (d) a
smart suggester, and (e) making the non-proxy connector plugins proxy-aware.

---

## Key design decision: proxy mode, not key injection

Two ways to "give a plugin our key":

| Mode | Key on machine? | Works for |
|---|---|---|
| **Proxy** (chosen) | No — only a tenant token + proxy URL | plugins that support a base-url override |
| Env injection | Yes — real key in `LUNA_<SLUG>_API_KEY` | any plugin (via `resolve_credential` env fallback) |

We standardise on **proxy mode** because the user explicitly wants keys uncompromised.
`plugin-connectors` (composio) already runs this way. The other connector plugins
(`funnelfighters`, `monday`, `render`, `giphy`, …) currently call their upstream
directly with a vault key — they need a small plugin-side change to consume
`ctx.vault.connect(slug)` (026.1) and route through the returned `Connection` (see
Workstream D). Env injection is kept only as an explicit, clearly-labelled per-binding
fallback for plugins that cannot be proxied.

---

## Data model (control plane)

Add a **plugin catalog + binding** table. One row per plugin we know how to key.

```
PluginCatalogEntry
  plugin_name      str   PK    # "plugin-funnelfighters"
  display_name     str
  marketplace_url  str | None
  category         str | None  # from manifest ("connectors", …)
  tier             str         # "default" (baked) | "supported" (opt-in)
  service_slug     str | None  # FK → GatewayService.slug (the key it uses)
  key_mode         str         # "proxy" | "env"   (default "proxy")
  suggested        jsonb       # auto-derived service suggestion (see suggester)
  enabled          bool        # admin can park an entry without removing it
  created_at / updated_at
```

Notes:
- `tier` is what makes the **two lists**. `default` rows mirror the baked
  `plugin_set`; `supported` rows are the opt-in catalog.
- A plugin needing extra non-secret params (e.g. funnelfighters `org_id`) keeps those
  in the gateway service config / per-agent override — *not* here. Only the secret is
  brokered through the pool.
- `service_slug` may point at a `GatewayService` that is **not** `provision_by_default`
  — provisioning is now membership-driven (below), so the global flag is no longer the
  only trigger.

---

## Provisioning logic (the core change)

`build_gateway_env` becomes membership-aware.

Effective service set for an agent =

```
{ s for s in services if s.provision_by_default }                      # LLM/base, unchanged
∪ { binding.service_slug
      for plugin in effective_plugins(agent)
      for binding in catalog where binding.plugin_name == plugin
      if binding.enabled and binding.key_mode == "proxy"
         and service(binding.service_slug).has_active_key }
```

`effective_plugins(agent)` =
- baked set: `image_config.plugin_set` for the agent's image (the **default** list), **plus**
- opt-in installs: plugins the agent installed from the **supported** list (tracked per
  agent — see Install hook).

The membership set decides what the **inventory discovery** endpoint (026.1) returns as
`provisioned` for the agent. The machine itself only gets the single `LUNA_GATEWAY_URL`
+ device token (026.1); plugins resolve via `ctx.vault.connect(slug)` (real vs virtual)
and connect at boot — no per-service env, no user step.

`key_mode == "env"` fallback: for a plugin that genuinely can't be proxied, inject the
decrypted real key as its specific env var (machine-scoped, compromises the key — admin
opt-in only).

### Applying to running machines

- New machines: env flows through `workflow.py` → `build_gateway_env` (already called).
- Existing machines on install / binding change: `fly.update_machine_env(machine_id,
  env_updates)` (already exists, recreates machine with new env). Triggered by the
  install hook and by admin "re-provision".

---

## Install hook (supported plugins)

The control plane must know when an agent installs an opt-in plugin so it can inject
that plugin's env. Options, simplest first:

1. **Control-plane-initiated install** (preferred for admin-driven installs): admin
   installs a supported plugin onto an agent from the UI → control plane calls the
   agent's install path **and** runs `build_gateway_env` delta → `update_machine_env`.
2. **Agent-reported install**: the agent reports its installed plugin set to the control
   plane (heartbeat/registration). Control plane diffs against catalog and, if a newly
   installed plugin has a binding, pushes the env delta + restarts.

Pick (1) for the admin flow now; add (2) later so user-initiated marketplace installs
also auto-provision. Record installed opt-in plugins on the agent
(`Agent.config_overrides["installed_plugins"]` or a small join table).

---

## Smart key suggestion

Per plugin, pre-fill a `GatewayService` proposal so the admin clicks "use suggestion"
instead of typing upstream URLs.

`suggest_service(plugin_manifest) -> dict`:
1. Read `credential_slots()` → gives `slug` + `env_key_var` (already the right names).
2. Look up `slug` in a built-in `KNOWN_SERVICES` map:

```python
KNOWN_SERVICES = {
  "funnelfighters": ("https://api.funnelfighters.io", "header:Authorization:Bearer", "FunnelFighters"),
  "monday":         ("https://api.monday.com/v2",      "header:Authorization",        "monday.com"),
  "render":         ("https://api.render.com/v1",       "header:Authorization:Bearer", "Render"),
  "giphy":          ("https://api.giphy.com/v1",        "query:api_key",               "GIPHY"),
  "composio":       (".../api/v3",                       "header:x-api-key",            "Composio"),  # exists
  # … grows as plugins are added
}
```

3. Unknown slug → fall back to `default_names(slug)` + a blank `upstream_url`/`auth_style`
   for the admin to complete, flagged "needs review".

This means most plugins arrive with a correct, one-click service suggestion. (Note:
`auth_style` gains a `query:<param>` variant for key-in-query APIs like GIPHY — small
addition to `parse_auth_style`/`_upstream_headers`.)

---

## Admin UI

### List A — Default plugin set (extend existing `DefaultsPage` / `PluginSetEditor`)
Each baked plugin row gains a **Key** control:
- "None" (default, current behavior) · "Use <service> pool key" (pick a gateway service
  with ≥1 active key) · "Configure key…" (opens the gateway service + add-key flow
  pre-filled from the suggester).
- Badge: green "keyed" when a bound service has an active key; amber "no key" otherwise.

### List B — Supported plugins (new `SupportedPluginsPage`, sibling tab under Defaults)
- Searchable marketplace list (reuses the marketplace search already in the editor).
- Each entry: bind a gateway key (same control as List A), `proxy`/`env` mode, enable
  toggle. **Not** added to `plugin_set` — only provisioned on install.
- Per-agent: "Install on agent" action → triggers the install hook.

Both lists call the existing `gateway/services` + `gateway/services/{slug}/keys`
endpoints to create services and add pool keys; the binding itself is a new
`/api/admin/plugin-catalog` CRUD.

---

## Keeping defaults current (new marketplace versions)

Today `plugin_set` entries are pinned by `version` + `sha256`, so the default set goes
stale when a plugin ships a new version. Add version freshness:

- **Auto (preferred):** per default-set entry, a `track: "latest" | "pinned"` flag.
  A periodic job (reuse the marketplace index already fetched by
  `fetch_index`/`fetch_and_verify`) compares each `track:"latest"` entry against the
  newest marketplace version; if newer, re-verify and rewrite the entry's
  `version`+`sha256`. Takes effect on the next image build / cache-warm and on new or
  re-provisioned machines — same path as any baked change. Default new entries to
  `latest`; let admins pin a specific version when they need stability.
- **Manual fallback (ship even if auto is deferred):** the Defaults / plugin-set editor
  shows "update available — vCURRENT → vLATEST" per row with an **Update** button that
  re-verifies the sha and rewrites the pinned entry. One click, no retyping.

Either way the bump only re-verifies + rewrites the pinned `{version, sha256}`; the
integrity gate (`fetch_and_verify`) still refuses a mismatched artifact.

---

## Workstreams

**A. Control-plane data + provisioning**
- `PluginCatalogEntry` model + migration.
- `/api/admin/plugin-catalog` CRUD (list/create/update/delete; tier filter).
- `suggest_service()` + `KNOWN_SERVICES` + `query:` auth style.
- `build_gateway_env` membership-aware (default set ∪ installed opt-in, key-gated).
- `update_machine_env` delta on binding change / install / re-provision.

**B. Install hook**
- Admin "install supported plugin on agent" → install + env delta + restart.
- Track installed opt-in plugins per agent.

**C. Admin UI**
- Key control in `PluginSetEditor` (List A).
- New `SupportedPluginsPage` tab (List B).
- Version freshness: per-entry `track: latest|pinned` + "update available → Update"
  button; auto-bump job comparing default-set entries to the marketplace index.

**D. Plugin side (luna-plugins repo — see 026.1 proposal)**
Make connector plugins use `ctx.vault.connect(slug)` (026.1) and build their client from
the returned `Connection` (base_url + secret), instead of a hardcoded upstream + raw
vault key. Audit each:
- `plugin-connectors` — already proxy mode ✅
- `plugin-funnelfighters`, `plugin-monday`, `plugin-render`, `plugin-giphy` — need the
  base-url override (currently vault + direct upstream).
- Leaf/no-key plugins (`recall`, `interview`, `mcp`, `charts`, `web-access`, …) — no
  binding needed.

---

## Sequencing

1. **A** (model, suggester, membership provisioning, catalog CRUD) — backend, testable
   with `plugin-connectors` end-to-end (already proxy-ready).
2. **C List A** — wire baked plugins to keys; ship "keyed default set".
3. **D** — make `funnelfighters`/`monday`/`render`/`giphy` proxy-aware (luna-plugins).
4. **C List B + B** — supported-plugins catalog + install-time provisioning.

Each stage is independently shippable; stage 1+2 already delivers instant-on baked
connectors for any proxy-ready plugin.

---

## Risks / open questions

- **Non-proxy plugins block the clean path.** Until D lands per plugin, those plugins
  either stay vault-only or use the `env` fallback (key on machine). List clearly in UI
  which plugins are proxy-ready.
- **Per-tenant non-secret params** (funnelfighters `org_id`, monday board ids): not a
  pool secret. Decide whether to auto-default via service config or keep user-entered.
- **Install detection for user-initiated installs** (hook option 2) is follow-up; v1
  covers admin-initiated installs + baked defaults.
- **Billing/metering**: non-LLM proxy calls record request counts (token scanner = 0) —
  a free bonus of per-plugin usage visibility; confirm we don't mis-bill.
- **Key scope**: pool keys can be `global` (shared across tenants) or `agent:<id>`
  (dedicated). Default bindings use global; allow per-agent override for big tenants.
