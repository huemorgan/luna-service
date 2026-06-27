# Plan 026.1 — Virtual keys in the vault + agent self-service

Refines plan 026 and **absorbs the old plan 027** (agent self-service) so Luna builds
the user-facing surface and the agent behaviour together, over one discovery layer.

026 makes the admin bind our pooled keys to plugins. 026.1 decides **how that surfaces
and gets used**: gateway-provided keys appear in the Luna **Key Vault** as a distinct
*type*, and the **agent** can see/suggest/connect them itself — all over one gateway
**inventory discovery** endpoint. Not a hidden env var, not a new local table.

The luna-side half (vault feature + agent tools/skill) is specced in
`plans/luna-proposals/026.1-vault-virtual-keys.md`. This file is the **control-plane**
half plus the shared design.

---

## The model: two key types, one of them virtual

The Key Vault shows two kinds of entries:

- **Real** — BYOK. The user pasted a secret; it's encrypted in `vault_credentials`
  (today's behavior, unchanged).
- **Luna-Service-Provisioned (virtual)** — no secret stored on the machine. A handle
  that routes through the central gateway. We provide the key; usage is metered and
  billed to the agent.

Installing a plugin that we key (e.g. browser) makes its **virtual key appear**
automatically — the user pastes nothing.

### No local gateway table

Rejected: a vault-side `gateway` table mirroring connections. The control plane is
already the source of truth (registry + key pool + per-agent bindings from 026), so a
local copy is pure sync cost. Instead:

- Virtual keys are a **live projection** from a control-plane discovery endpoint,
  unioned into the Key Vault list at render/resolve time (short cache).
- The only machine-local state is **one base URL** (already known — the agent routes
  LLM through the same host) + the **device token**. Nothing to configure, no migration.

"Populate on install" then falls out for free: install → binding created centrally →
the next discovery call returns it → the virtual key shows up. No local write.

---

## Control-plane deliverables (luna-service)

### 1. Gateway inventory discovery (one endpoint, two consumers)
`GET /api/agent/gateway/services` — authed by the device token
(`token_svc.verify_token`, same as the proxy). Secrets-free. This is the **single
inventory** of what the gateway offers a given agent — consumed by **both** the vault UI
(to project virtual keys) **and** the agent (to reason/suggest/connect). Returns, for
the calling agent:

```json
[
  { "slug": "browser-use", "display_name": "Browser Use", "purpose": "browser automation",
    "proxy_url": "{base}/proxy/browser-use", "auth_header": "X-Browser-Use-API-Key",
    "auth_scheme": null, "provisioned": true, "has_key": true, "status": "active" },
  { "slug": "monday", "display_name": "monday.com", "proxy_url": "{base}/proxy/monday",
    "auth_header": "Authorization", "auth_scheme": "Bearer",
    "provisioned": false, "has_key": true, "status": "available" }
]
```

- `provisioned` = bound to a plugin this agent has (the agent's virtual keys).
- `has_key` = the pool has an active key for this agent (global or agent-scoped).
- `available` (not provisioned) = the menu the agent/user can add from.
- Never returns a key value.

This is the single source the vault projects from. (Plan 027's agent self-service reads
the same endpoint.)

### 2. Provisioning: one URL + one token (not per-service env)
Replace per-service env injection for **plugins** with a single pair:

```
LUNA_GATEWAY_URL   = {base}/proxy
LUNA_GATEWAY_TOKEN = lsv1-…   # this agent's device token (issue_token, rotated per provision)
```

The vault builds `{LUNA_GATEWAY_URL}/<slug>` per connection on demand. Keep the
SDK-standard LLM vars (`ANTHROPIC_BASE_URL`, `OPENAI_API_KEY`, …) exactly as today —
pydantic-ai reads those directly; only the *plugin* connector env collapses to the
generic pair. `build_gateway_env` change in `cloud/gateway/provision_env.py`.

### 3. Bindings + install hook (from 026)
- Per-agent binding membership (026 catalog) decides what discovery marks
  `provisioned`.
- Install of a keyed plugin → create/enable the binding centrally → it becomes a
  virtual key. v1: admin/control-plane-initiated install; user-initiated marketplace
  installs report in later (027).

### 4. Guardrails
- Per-agent allow/deny + optional budget enforced at the proxy (metering already
  attributes per agent+service via `record_usage`).
- Ensure non-LLM proxy calls are attributed (request counts even when the token scanner
  yields 0) so virtual-key usage shows up per agent.

---

## Agent self-service (merged from 027)

The same discovery inventory + `vault.connect()` lets the agent solve key problems
itself — no user step, no key exposed. Lives in **plugin-vault** (not a separate
plugin), specced in the proposal:

- The agent already holds one universal device token, so reaching any pooled service is
  discovery + knowledge, not new plumbing.
- Tools: `list_available_gateway_keys()` (the inventory), `connect_gateway_key(slug)`
  (creates the virtual key / asks host to bind), and an escape hatch to call the proxy
  directly for ad-hoc / user-written code.
- Skill: external keys are brokered + billed to this workspace → check the inventory and
  connect instead of asking the user for a key; if we don't pool it, say so and offer
  BYOK.
- Auto-connect loop: a plugin that loads inactive → look up its binding → connect if a
  key exists → else honest "no key", no looping.
- **User-developed plugins** get the same deal: `ctx.vault.connect(slug)` (or proxy
  directly) — broad access is safe because usage is metered to the paying workspace.

### Guardrails (control-plane)
- Per-agent **allow/deny + optional budget** enforced at the proxy (metering already
  attributes per agent+service via `record_usage`).
- Device token is the blast radius: per-agent, revocable, only authorizes services with
  a pooled key. Real keys never leave the gateway.
- Audit `connect_gateway_key` per agent.

---

## Resolution contract (shared with the luna proposal)

`vault.connect(slug)` returns a `Connection`:

| Type | base_url | secret | billed |
|---|---|---|---|
| Real (BYOK) | plugin's real upstream | the stored secret | no (user's own account) |
| Virtual | `{LUNA_GATEWAY_URL}/<slug>` | device token | yes (metered to agent) |

Precedence: **real BYOK overrides virtual** (an explicit user key wins); else virtual if
`provisioned && has_key`; else not connected.

---

## What lives where

- **luna-service (this plan):** inventory discovery endpoint, single-pair provisioning,
  bindings + install hook, proxy guardrails (allow/deny + budget). *Central, no per-image
  setup.*
- **luna / plugin-vault (proposal `026.1-vault-virtual-keys.md`):** virtual key *type*,
  live projection into the Key Vault tab, `vault.connect()`, **and the agent self-service
  tools + skill** (merged 027). **No local gateway table.**
- **luna-plugins:** per-plugin adoption — `ctx.vault.connect(slug)` instead of
  hardcoded base_url + raw key.

---

## Sequencing

1. Inventory discovery endpoint + single-pair provisioning (testable with curl + device
   token).
2. Vault proposal lands → Key Vault shows virtual keys, `vault.connect()` resolves.
3. Per-plugin adoption (start with `plugin-connectors`, already proxy-shaped).
4. Agent tools + skill + auto-connect loop (same plugin-vault surface).
5. Install hook + guardrails so keyed installs auto-show their virtual key, bounded by
   allow/deny + budget.

Depends on 026 (registry, pool, bindings, suggester).
