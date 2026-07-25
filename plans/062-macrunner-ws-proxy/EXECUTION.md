# Execution summary — 062 MacRunner WebSocket proxy

## What was built
- **`cloud/api/proxy.py`** — `@router.websocket("/a/{agent_slug}/{path:path}")`: accepts a client WS, resolves the tenant agent, wakes it if suspended, dials the tenant Luna's internal `wss://…/{path}` with `x-luna-proxy-secret` (+ `x-luna-user`, `fly-force-instance-id`), and pumps frames both ways (`_ws_pump`) until either side closes.
- **Auth model** — MacRunner's pairing path (`…/api/p/luna-macrunner/ws`) is forwarded by slug and gated by the **tenant plugin token** (the native app has no browser session). Every other WS path requires the owner's **session + membership** (mirrors the HTTP `_resolve_agent`).
- **`X-Luna-Public-Base`** header injected on the HTTP proxy so plugins can emit reachable public URLs (the plugin's `/pair` consumes it).
- **`cloud/pyproject.toml`** — added `websockets>=12` (for the upstream dial; `uvicorn[standard]` already handles the server side).

## Verified
- `ast.parse` clean; `import cloud.api.proxy` succeeds; the WS route registers (`/a/{agent_slug}/{path:path}` present). `websockets 16.1` importable in the venv.
- **Additive only** — no change to existing HTTP proxy behavior (new route + one response header).

## NOT verified
- **No real hosted E2E.** The local checkout has no control-plane DB/config, so I could not run the control plane and drive app → proxy → tenant → plugin. Full verification needs one hosted Luna + a paired Mac.

## Shipped
- Commit **`f3d5942`** on `main`, pushed to `origin/main` → Render auto-deploy. Only the 3 files above (the rest of the working tree — `gateway_proxy.py`, `ui/*`, `website/*` — was left uncommitted).

## Security note
The macrunner WS path is unauthenticated at the proxy and gated solely by the tenant plugin token (owner-issued, strong secret). Approved by the owner. Follow-ups: hash/vault the pairing token; optional rate-limit on the forward path.
