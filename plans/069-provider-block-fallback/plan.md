# Plan 069 — Provider-block resilience (kimi-k3 HTML 403, Anthropic credit 400)

## Incidents

1. **2026-08-02, vaselin-luna-bug-fixer**: every kimi-k3 turn died with
   `status_code: 403 … body: <!DOCTYPE html>… Blocked`. Moonshot's edge/WAF
   blocks the gateway's datacenter egress IP (a residential IP gets normal
   JSON 401s from `api.moonshot.ai`), and the agent runtime classified the
   403 as an auth/config error — no chain fallback → raw error to the user.
2. **2026-07-31, vaselin-devops-ff**: Anthropic `400 credit balance is too
   low` on the pinned summarization chain mapped to `InvalidRequestError`
   (non-fallback) → the read tool degraded into the endless paginate spiral.

## Root class

"Provider became unusable" (edge block, account billing) was classified as
"caller made a bad request", which by design never fails over.

## Fix (luna 0.64.002, commit 787f6ba)

- `luna/agent/runtime.py`: `_is_edge_block()` — a 401/403 `ModelHTTPError`
  whose body is an HTML page falls back under **every** policy, like a 5xx.
  JSON-bodied 401/403 still surfaces loudly (real key problems must be seen).
- `luna/llm/providers/anthropic.py`: `_bad_request_kind()` — 400s mentioning
  credit/billing map to `ProviderDownError` (fallback + cooldown) instead of
  `InvalidRequestError`; context-length handling unchanged.
- `tests/069-provider-block-fallback/` — 8 tests pinning both behaviors.
  Full suite: same 33 pre-existing env failures as clean baseline, no
  regressions.

## Not fixed here

- Moonshot blocking the gateway egress IP itself (ops: different egress or
  Moonshot support ticket). The fix makes agents degrade gracefully, and a
  single-model chain (picker writes chain=[selected]) still errors the turn —
  but with cooldown + a clean failure instead of repeated HTML dumps.
- Read-tool bounded degradation (paginate spiral hardening) — still pending.

## Rollout

Rides the same image rollout as 067 (chat-ui 0.4.1 already published to the
marketplace). Build the image from luna main at ≥0.64.002 — supersedes the
0.55.001 version in 067's instructions:

    rollout_image.py pin --plugin plugin-chat-ui --plugin-version 0.4.1 \
        --sha256 5e2d38f27aa3375f4cd152f11e50314dcab3f7d12eec6e5947dfec2373d9389c
    rollout_image.py build --branch main --version 0.64.002
    rollout_image.py promote --version 0.64.002
    rollout_image.py verify --version 0.64.002

Then the fleet plugin-chat-ui bulk upgrade → 0.4.1, and verify on a tenant:
picker gauge/selection/purple (067) + kimi-k3 turn falls back instead of
dumping the Blocked page (069).
