# Plan 077 — Token-gated HTTP pass-through for the playbook delegation card

Executes **Part B of plugin-playbooks plan 014** (that repo,
`plans/014-hosted-card-base-path/PLAN.md`). Part A shipped as
plugin-playbooks 0.25.3 on 2026-08-29.

## Problem

The playbook delegation progress card is embedded in chat as an
opaque-origin srcdoc iframe (`sandbox="allow-scripts allow-downloads"`): it
can send neither the session cookie nor a bearer header. On hosted tenants
its status poll (`GET /a/{slug}/api/p/plugin-playbooks/delegations/{id}/card
?token=…`) hits `proxy_to_luna`, which unconditionally requires a session
(`_resolve_agent`) → 401 → the card lands on its honest offline state
("Working — live updates can't show here") and never shows live progress.

The tenant route needs no proxy auth: it is capability-scoped by a random
per-delegation token minted at creation and baked into that one card's HTML
(`secrets.compare_digest`, one 404 for unknown id AND bad token — no
token-validity oracle), read-only, and already serves
`Access-Control-Allow-Origin: *`.

## Fix

HTTP twin of plan 062's `_TOKEN_GATED_WS_SUFFIXES` (MacRunner WS), in
`cloud/api/proxy.py`:

1. `_TOKEN_GATED_GET_PATHS` — anchored regex matching exactly
   `api/p/plugin-playbooks/delegations/{id}/card`.
2. In `proxy_to_luna`: a GET whose path matches is handed to
   `_proxy_token_gated_get` — resolve agent by slug (404 if unknown),
   forward with no session; the tenant's token check is the auth.
3. **Never wake.** Unlike the WS path, a stopped/error machine returns 503
   instead of waking: a stopped machine cannot be running a delegation, and
   an unauthenticated poll must not be able to keep a tenant awake (billed).
   The card degrades to its offline state.
4. `_proxy_request` accepts `user=None` and only sets `x-luna-user` when a
   user exists (it already strips cookies). The tenant has no global
   proxy-secret middleware — only `/api/auth/proxy-login` consumes those
   headers — so a sessionless forward is safe.

## Security

- Auth model identical to plan 062's WS precedent: proxy forwards by slug,
  tenant verifies the capability token. Worst case for an attacker who
  guesses a slug: read-only 404s from the tenant, or a 503 — no wake, no
  oracle, no session material forwarded (cookies stripped, no x-luna-user).
- GET-only, exact-path regex (anchored; `..` segments cannot match).
- Existing authenticated HTTP paths unchanged.

## Testing

- `cloud/tests/test_proxy_token_gate.py` — forwarded sessionless (user=None);
  unknown slug 404; stopped agent 503 with `_try_wake_agent` never called;
  POST and other paths still 401; upstream failure 502; header construction
  omits `x-luna-user` when sessionless, keeps it with a user.
- Full hosted E2E needs a real tenant (as in plan 062) — see
  `tests/077-playbook-card-token-gate/SCENARIOS.md`.

## Rollout

Additive, limited blast radius. Merge to `main`, Render deploys. Then start
a fresh delegation on a hosted tenant: the new card should show live
progress. Old cards in chat history stay offline (HTML baked into past
messages, polling already stopped).
