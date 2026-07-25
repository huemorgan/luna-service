# Plan 062 — WebSocket reverse-proxy for MacRunner (and future WS plugins)

## Problem
The control-plane proxy (`cloud/api/proxy.py`) forwards HTTP to a tenant's Luna via httpx. It has **no WebSocket support**. The MacRunner app connects to a plugin's `wss://…/api/p/luna-macrunner/ws` endpoint; on a **hosted** Luna that connection must traverse the control plane, which currently drops the upgrade. So MacRunner works against a local Luna but not a hosted one.

## Auth model (the crux)
The MacRunner app is a **native app with no browser session** (deliberately — no OAuth in the app). So the pairing WS can't use `get_session` (cookie auth). Instead:

- **MacRunner pairing WS** (`…/api/p/luna-macrunner/ws`): forwarded by **agent slug** (public, in the URL) and gated by the **plugin pairing token** carried in the query and verified **at the tenant plugin** (`state.verify_token`). Possession of the token = authorized — the same model as local. The proxy is a dumb, token-agnostic forwarder for this path.
- **Every other WS path**: requires the owner's **session** (browser clients), mirroring the HTTP proxy's `_resolve_agent` (membership-checked).

Both inject `x-luna-proxy-secret` (derived per agent) so the tenant accepts the proxied connection, and `fly-force-instance-id` for routing.

## Public pairing URL
A hosted plugin can't know its public address (its `request.base_url` is the *internal* URL). Fix: the HTTP proxy injects **`X-Luna-Public-Base: {scheme}://{public_host}/a/{agent_slug}`** on every proxied request. The plugin's `/pair` uses that header when present to emit `wss://{public_host}/a/{agent_slug}/api/p/luna-macrunner/ws`, falling back to `request.base_url` for local.

## Changes
1. **luna-service `cloud/api/proxy.py`**
   - `@router.websocket("/a/{agent_slug}/{path:path}")` — resolve agent (token-path: by slug; else session+membership), wake if suspended, accept client, dial `wss://{internal}/{path}?{query}` with proxy headers, pump frames both ways.
   - Inject `X-Luna-Public-Base` in `_proxy_request` headers.
2. **luna-service deps** — add `websockets` (httpx can't do WS).
3. **plugin `routes.py`** — `/pair` prefers `X-Luna-Public-Base`.

## Testing
- Unit: import check; `X-Luna-Public-Base` construction; pump text/bytes round-trip with a fake upstream.
- **Full hosted E2E needs a real tenant** (a hosted Luna + a paired Mac) — cannot be run from a local checkout (no local control-plane DB/config). This is called out honestly; the change is **additive** (new WS route + one response header), so it doesn't alter existing HTTP proxy behavior.

## Rollout
Additive + limited blast radius. Deploy luna-service (Render, `main`) and republish the plugin. Verify against one hosted tenant before announcing.

## Security review
- The macrunner WS path is **unauthenticated at the proxy** and gated only by the tenant plugin token. Risk: an attacker can open an upstream WS to any agent's macrunner endpoint, but without a valid token the tenant closes it (4401). Cost is a short-lived upstream dial per attempt — acceptable; rate-limiting can be added if abused. Tokens must be strong (they are: `secrets.token_urlsafe(24)`) and should move to hashed+vault storage (tracked separately).
- No change to existing authenticated HTTP proxy paths.
