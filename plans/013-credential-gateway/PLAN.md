# Plan 013 — Credential Gateway

The proxy layer that lets us provide third-party API keys (LLMs, Composio,
Tavily, anything a plugin needs) to tenant Lunas **without the key ever
existing on the tenant machine**. We pay the provider, meter the usage, and
charge the customer.

Origin: Luna shipped 007 (provider base-url override, vault keys, BYOK) and
answered our recommendation in
`luna/plans/007-provider-base-url/luna-service-response.md`. This plan is our
side of that contract, plus the two-level key model and dynamic service
registry the platform needs. The Luna-side asks that this plan depends on live
in `luna/plans/007-provider-base-url/007.001/RECOMMENDATION.md`.

---

## The naming contract (read this first)

Today every layer invents its own name for the same key. This plan fixes that
with one rule:

> **Every external service has one canonical `slug`.** All names derive from
> it mechanically.

| Derived name | Pattern | Example (`slug=composio`) |
|---|---|---|
| Vault credential (Luna) | `{slug}_api_key` | `composio_api_key` |
| Env key var (Luna) | `LUNA_{SLUG}_API_KEY` | `LUNA_COMPOSIO_API_KEY` |
| Env base-url var (Luna) | `LUNA_{SLUG}_BASE_URL` | `LUNA_COMPOSIO_BASE_URL` |
| Proxy mount (luna-service) | `/proxy/{slug}/` | `/proxy/composio/` |
| Key pool rows (luna-service) | `service_slug = {slug}` | `service_slug = 'composio'` |

Known deviation: `plugin_connectors` currently uses the vault name
`plugin_connectors.composio.api_key`. The 007.001 recommendation asks Luna to
adopt the canonical name (or alias it). Until then, the registry carries an
explicit `luna_credential_name` override per service — the registry is the
adapter for any legacy naming.

## Architecture

```
Tenant Luna (Fly machine)                luna-service (Render)                 Upstream
─────────────────────────                ─────────────────────                 ────────
LUNA_ANTHROPIC_API_KEY=lsv1-<tenant>     /proxy/anthropic/v1/messages
LUNA_ANTHROPIC_BASE_URL=                   ├─ token starts with lsv1-?
  https://luna.com.ai/proxy/anthropic      │   yes → authenticate tenant
                                           │         resolve key (2 levels, below)
                                           │         inject real key
                                           │         meter for billing
                                           │   no  → BYOK passthrough:
                                           │         forward credential unchanged
                                           │         meter visibility only, NO billing
                                           └─ forward ────────────────────►  api.anthropic.com
```

One pattern, every service. Anthropic, OpenAI, Composio, Tavily are registry
rows, not code paths.

### 1. Service registry — `gateway_services`

What makes services dynamic. Adding a service = inserting a row (admin UI or
seed), zero proxy code changes.

```
gateway_services
  slug                  text PK         -- "anthropic", "composio", "tavily"
  display_name          text            -- "Anthropic"
  upstream_url          text            -- "https://api.anthropic.com"
  auth_style            text            -- how the upstream wants the key:
                                        --   "header:x-api-key"
                                        --   "header:Authorization:Bearer"
  luna_credential_name  text            -- vault name Luna uses; default "{slug}_api_key";
                                        -- override for legacy names
                                        -- ("plugin_connectors.composio.api_key")
  luna_env_key_var      text            -- default "LUNA_{SLUG}_API_KEY"
  luna_env_base_url_var text            -- default "LUNA_{SLUG}_BASE_URL"
  enabled               bool
  provision_by_default  bool            -- inject into new tenants automatically
  created_at / updated_at
```

Seed rows: `anthropic`, `openai`, `tavily` (have keys today), `composio`
(when we buy the workspace plan), `openrouter` (when needed).

### 2. Key pool — `gateway_keys` (the two levels)

```
gateway_keys
  id              uuid PK
  service_slug    text FK -> gateway_services
  scope           text            -- "global" | "agent:{agent_id}"
  priority        int             -- 1 = primary, 2 = first fallback, ...
  api_key_enc     bytea           -- encrypted with CLOUD_VAULT_ROOT_KEY-derived key
  label           text            -- "anthropic-main", "anthropic-backup"
  is_active       bool
  cooldown_until  timestamptz NULL  -- set on upstream auth/429 failures
  last_used_at / created_at
  UNIQUE (service_slug, scope, priority)
```

**Resolution for service S, tenant agent A** (only after tenant auth):

1. `scope = 'agent:{A}'`, active, not cooling down, priority asc — the
   **machine-specific override**. Still injected at the proxy; the machine
   never sees it.
2. `scope = 'global'`, active, not cooling down, priority asc — the
   **service-wide chain with fallback** (your "main key with a fallback").
3. Nothing left → 502 to Luna with a clear error body. Luna's router
   cooldown/fallback chain takes it from there.

**Fallback semantics:** if the upstream answers 401/403/429 with key K, mark
K `cooldown_until = now() + interval` (401/403: long + alert, it's probably
revoked; 429: short, it's rate pressure) and retry the request once with the
next key in the chain. Two keys on the same request max — beyond that return
the upstream error.

### 3. The universal proxy — `/proxy/{slug}/{path:path}`

One FastAPI route, streaming-capable (SSE for LLMs):

1. Look up `slug` in registry (cached in memory, refreshed on change). 404 if
   unknown/disabled.
2. Extract the incoming credential from wherever `auth_style` says it lives.
3. **`lsv1-` prefix → managed flow:** validate tenant token (constant-time,
   maps to agent_id), resolve key per §2, swap credential, forward, meter
   **billable**.
4. **Anything else → BYOK passthrough** (contract Luna gave us): forward the
   credential unchanged, never substitute our key, never log/persist it,
   meter **visibility-only, never billed**. If their key fails upstream,
   return the error verbatim — no fallback to our keys.
5. Stream the response back. Capture usage (LLM token counts from response
   bodies where parseable; request counts otherwise) into `usage_events`.

```
gateway_tenant_tokens
  token_hash     text PK         -- sha256; raw token only at issue time
  agent_id       uuid FK
  created_at / revoked_at

usage_events
  id             uuid PK
  agent_id       uuid
  service_slug   text
  billable       bool            -- false for BYOK passthrough
  key_id         uuid NULL       -- which pool key served it (NULL for BYOK)
  request_count  int
  input_tokens / output_tokens   int NULL  -- LLMs only
  created_at
  -- aggregated into usage_rollups by a periodic task (012.4 territory)
```

### 4. Provisioning becomes registry-driven

`cloud/provisioning/workflow.py` today hardcodes three env var names. Replace
with:

```python
for svc in await registry.provisionable_services():
    env_vars[svc.luna_env_base_url_var] = f"{PUBLIC_URL}/proxy/{svc.slug}"
    env_vars[svc.luna_env_key_var] = tenant_token   # one lsv1- token per agent
env_vars["LUNA_HOST_NAME"] = "Luna Cloud"           # branding, per Luna's 007 response
```

The machine gets proxy URLs + one tenant token + zero real keys. Existing
agents migrate on their next reprovision; a backfill admin action re-injects
env on running machines.

### 5. Admin UI (Services page)

- List services from the registry; enable/disable; add a service via form
  (slug, upstream, auth style).
- Per service: key pool table — add/rotate/deactivate keys, see priority,
  cooldown state, last-used. Key values write-only (paste once, never
  displayed).
- Per agent (agent detail page): "Credential overrides" card — attach an
  agent-scoped key for any service. Same write-only handling.
- BYOK visibility: per agent, per service, show `managed | byok | none`
  derived from recent `usage_events` (and optionally Luna's
  `GET /api/llm/providers` transparency endpoint).

## How the Composio mapping works end-to-end (worked example)

This answers "how does Luna's Composio need map to the key we provide":

1. Registry row: `slug=composio`, `upstream_url=https://backend.composio.dev`,
   `auth_style=header:x-api-key`,
   `luna_credential_name=plugin_connectors.composio.api_key` (legacy override).
2. We buy one Composio workspace key, insert it as
   `gateway_keys(service_slug='composio', scope='global', priority=1)`.
3. Provisioning injects into the machine:
   `LUNA_COMPOSIO_BASE_URL=https://luna.com.ai/proxy/composio` and
   `LUNA_COMPOSIO_API_KEY=lsv1-<tenant-token>`.
4. **(Needs Luna 007.001)** `plugin_connectors` reads those env vars at boot
   and constructs `ComposioProvider(api_key=<token>, base_url=<proxy>,
   auth_mode="gateway")` — the gateway auth mode already exists in the
   provider, it just isn't env-wired yet.
5. Luna calls "list my Gmail triggers" → plugin hits
   `luna.com.ai/proxy/composio/api/v3/...` with the tenant token in
   `x-api-key` → proxy swaps in the real workspace key → Composio responds →
   usage metered to the tenant.
6. If the tenant later stores their own Composio key in the vault, vault beats
   env (Luna's rule), the proxy sees a non-`lsv1-` key, and passthrough+no-bill
   kicks in automatically. Same machinery as LLM BYOK.

## Dependencies on Luna (asks filed in 007.001)

| # | Ask | Blocking what |
|---|---|---|
| 1 | Env-wired gateway mode for `plugin_connectors` (Composio base_url + key from env) | Composio through the proxy (§ example step 4) |
| 2 | Same pattern for Tavily / web-access plugin | Tavily through the proxy |
| 3 | Credential manifest endpoint (machine-readable list of every credential slot + env var names) | Registry seeding & drift detection; nice-to-have, not blocking |
| 4 | Canonical naming convention adopted for new plugins (`{slug}_api_key`) | Keeps `luna_credential_name` overrides from multiplying |

LLM providers (anthropic/openai/openrouter) are already done — Luna 007
shipped them. We can ship phases A–C below against LLMs alone, then pick up
Composio/Tavily when 007.001 lands.

## Phases

### A. Gateway core
- [ ] Tables: `gateway_services`, `gateway_keys`, `gateway_tenant_tokens`,
      `usage_events` + migrations; encryption helpers reusing the vault
      keygen pattern (`cloud/vault/keygen.py`)
- [ ] Registry CRUD + in-memory cache; seed anthropic/openai/tavily
- [ ] `/proxy/{slug}/{path}` route: tenant-token flow, key resolution
      (agent → global, priority, cooldown), header injection per
      `auth_style`, SSE/streaming forward
- [ ] Key fallback on 401/403/429 + cooldown + admin alert on auth failures
- [ ] Tenant token issue/verify (`lsv1-` prefix, hash at rest), one per agent,
      issued at provision time

### B. BYOK passthrough (Luna's contract)
- [ ] Non-`lsv1-` credential → passthrough unchanged, no key substitution,
      no fallback-to-ours, no logging of the credential
- [ ] Visibility-only metering (`billable=false`)

### C. Metering
- [ ] Parse usage from Anthropic/OpenAI response streams (token counts)
- [ ] `usage_events` writes on every proxied call; rollup task into
      per-agent daily aggregates
- [ ] Agent detail page: usage card (requests + tokens by service, managed
      vs BYOK)

### D. Provisioning + migration
- [ ] Registry-driven env injection (replaces the hardcoded three-var loop in
      `workflow.py` and the fly/docker runtimes); inject `LUNA_HOST_NAME`
- [ ] Stop injecting real LLM keys entirely
- [ ] Admin action: re-inject env on existing agents (reprovision path)

### E. Admin UI
- [ ] Services page (registry + key pools, write-only key entry)
- [ ] Agent detail: credential overrides card + usage card

### F. Composio + Tavily activation (after Luna 007.001)
- [ ] Enable composio/tavily registry rows with `provision_by_default`
- [ ] Dojo: tenant Luna lists Composio connectors with zero Composio key on
      the machine

## Exit criteria

- [ ] A fresh tenant machine's env contains **no real provider key** (verify
      via `fly machine exec env` / docker inspect) and chat works end-to-end
      through `/proxy/anthropic`
- [ ] Revoking the global priority-1 Anthropic key flips traffic to
      priority-2 with no tenant-visible outage (one retried request max)
- [ ] An agent-scoped key for one agent routes only that agent's traffic;
      all other agents stay on the global chain
- [ ] Tenant stores own Anthropic key in their vault → proxy passes through,
      `usage_events.billable=false`, no double-billing
- [ ] Adding a brand-new service (e.g. a stub echo API) via the admin UI
      makes it provisionable with zero code changes
- [ ] No raw key or passthrough credential appears in any log or DB column
      (grep + schema audit)

## Non-goals

- Pricing/charging logic (012.4 / billing phase consumes `usage_events`)
- Per-tenant rate limiting policy (proxy has the hook point; policy is a
  later phase)
- OAuth-style per-user connector auth flows (Composio handles those
  upstream; we only manage the workspace key)
