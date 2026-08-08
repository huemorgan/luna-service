# 050 — Enable Gemini (working + billed), promote full model set to every machine, default → Sonnet

## Goal

Three coupled things, all landing on the whole fleet:

1. **Make Gemini a real, non-crashing agent model.** Today a Gemini pick
   would crash: the hosted runtime sends Gemini straight to Google's native
   SDK (which ignores our gateway base_url), using a *gateway token* as if it
   were a Google key → Google 401s, and even if it ran, the spend would bypass
   unified billing. Route Gemini through the gateway on Google's
   **OpenAI-compatible** surface (same trick as Grok), price it, and gate it.
2. **Promote every model we support to all machines.** Re-push the current
   catalog + resolved heads env to every live agent so pickers match prod.
3. **Default reasoning model → Claude Sonnet 4.5 for everyone.** Change the
   catalog `recommended_default` and re-resolve/re-push heads so every machine
   (without an explicit per-agent override) runs Sonnet as primary.

## Why Gemini can't work today (confirmed)

- Gateway **service** exists in prod: `gemini`, enabled, `key_count=1`,
  upstream `https://generativelanguage.googleapis.com/v1beta`, `auth=query:key`.
  Used today only for **image gen** (`gemini.generate`,
  `/models/{m}:generateContent`).
- Luna runtime (`luna/luna/agent/runtime.py:340-354`) builds Gemini via
  pydantic-ai `GoogleModel` + native `google-genai` client — **no hooked
  client, base_url ignored**. So chat turns never traverse our gateway.
- Billing pricing v1 (`cloud/billing/seed.py`) covers only Gemini **image**
  models (`gemini-3-pro-image`, `gemini-2.5-flash-image`). Gemini **text**
  models are in neither tier list → `model_uncovered` → `sku_unpriced` →
  **402 block in enforce mode** = crash.
- `route_catalog` has no Gemini chat route → unknown route → also
  `sku_unpriced`.

So "add a catalog row + repush env" alone = a selectable model that 402s on
first turn. All four layers (runtime, gateway route, pricing, catalog) must
move together.

## Design decisions

- **Transport: OpenAI-compat, mirror Grok.** Google exposes an OpenAI-chat
  endpoint at `…/v1beta/openai/chat/completions`. Route the agent through
  `OpenAIChatModel` + `build_hooked_client()` (billing headers + gateway
  base_url), exactly like xAI. No new SDK, no native-client hang.
- **Path shape.** Agent base_url for gemini → `/proxy/gemini/openai`; the
  OpenAI SDK appends `/chat/completions` → gateway forwards to
  `{upstream}/openai/chat/completions` = `…/v1beta/openai/chat/completions`.
  Keeps the single `gemini` service (native image routes untouched).
- **Auth.** Google's OpenAI-compat accepts the key as `?key=` (same as native
  v1beta), so the existing `auth=query:key` service works unchanged. **Verify
  in Phase 1** with a direct curl; if it demands `Authorization: Bearer`,
  fall back to a dedicated `gemini-openai` service (Bearer) — documented as the
  Plan B below.
- **Billing adapter.** Add `gemini.chat` = OpenAI-chat wire shape (reuse
  `OpenAIChatCollector`); `provider_for_adapter("gemini.chat") == "gemini"`
  so events/catalog attribute to gemini correctly.
- **Pricing is additive + immutable.** New `provider_cost` v2 (adds gemini
  token rates) and `commercial_pricing` v2 (adds gemini text models to tiers).
  Existing models/values copied forward verbatim — no economics change for
  anything else.
- **Model tiers.** `gemini-3-pro` → top tier (flagship reasoning);
  `gemini-2.5-flash` → mid tier.
- **Default → Sonnet.** Flip `recommended_default` off `claude-opus-4-6`, on
  `claude-sonnet-4-5-20250929` for the reasoning kind. `resolve_default_heads`
  then yields Sonnet as primary for every machine without an explicit
  override; re-push env fleet-wide.

## Phases

### Phase 1 — Gateway: serve Gemini chat (luna-service)
- Verify Google OpenAI-compat auth mode (curl `?key=` vs Bearer) with the prod
  Gemini key.
- `cloud/gateway/adapters.py`: add `GeminiChatCollector` (subclass/alias of
  `OpenAIChatCollector`), register `"gemini.chat"`, add to `_OPENAI_CHAT_COMPAT`.
- `cloud/gateway/route_catalog.py`: add
  `("gemini","POST","/openai/chat/completions") → billed("gemini.chat","llm_call")`
  and `("gemini","GET","/openai/models"[/*]) → _FREE`.
- `cloud/api/gateway_proxy.py`: add `"gemini"` to `_MODEL_GATED_PROVIDERS`.
- Unit tests for classify + collector.

### Phase 2 — Billing: price Gemini text (luna-service)
- `cloud/billing/provider_rates_v1.py` → new `provider_rates_v2` with gemini
  `llm_call` input/output token rates (from Google pricing).
- New pricing seed: provider_cost v2 + commercial v2 (copy v1 config, add
  `gemini-3-pro` to `top_tier_models`, `gemini-2.5-flash` to `mid_tier_models`).
  Publish (immutable).
- Tests: rating covers gemini text; publish accepts the enabled gemini rows.

### Phase 3 — Catalog rows (luna-service + prod)
- `cloud/gateway/model_registry.py`: add `gemini-3-pro` (reasoning) and
  `gemini-2.5-flash` (reasoning, summarization). Remove legacy Sonnet 4 seed
  once Phase 5 confirms no machine is pinned to it.
- Insert the two gemini rows into prod `gateway_models` via
  `POST /api/admin/gateway/models`.

### Phase 4 — Luna runtime (submodule) + image
- `luna/luna/agent/runtime.py`: route `provider == "gemini"` through
  `OpenAIChatModel` + `_PaiOpenAI(base_url=…, http_client=build_hooked_client())`;
  base_url = `gemini_base_url` (gateway) with `/openai` suffix, else Google's
  public OpenAI-compat URL for local/BYOK. Bump `__version__`.
- Follow `skills/luna-submodule-changes` lineage rules (deploy branch), build
  the hosted image, set as Main.

### Phase 5 — Default → Sonnet + fleet env repush
- Flip `recommended_default` in prod `gateway_models` (opus off, sonnet on) via
  `PATCH /api/admin/gateway/models/{id}`; update `model_registry.py` seed to
  match.
- Roll the new Luna image to all agents; for each, `PATCH
  /api/admin/machines/{id}/models` (no override) so it re-resolves to Sonnet
  and receives the fresh `LUNA_MODEL_CATALOG` + `LUNA_PRIMARY_MODEL`.
- Confirm no agent head pinned to `claude-sonnet-4-20250514`; then delete the
  legacy catalog row.

### Phase 6 — Verify in production (browser)
- On a test Luna: pick **Gemini 3 Pro**, run a turn → succeeds (no 402/crash),
  charge appears on the Usage page under that Luna, `billable_events` shows
  `provider=gemini`.
- Confirm a machine's picker lists the full set and primary resolves to Sonnet.

## Rollback
- Pricing v2 is additive; revert = publish v3 restoring v1 tiers (never edit a
  published version).
- Catalog rows: `enabled=false` to hide Gemini instantly.
- Default: flip `recommended_default` back to Opus + repush.
- Runtime: redeploy prior image.

## Risk
- Medium. New published pricing version affects all future rating (mitigated:
  additive, existing values copied verbatim). Fleet image rollout + env repush
  is the same mechanism used for the xai fix (26/26 done there).
