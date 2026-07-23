# 054 — Moonshot AI (Kimi) provider + catalog rows

## Context

Roy asked for Kimi models in the selection menu — "their top and mid model, in
our high and mid cost tiers". Research (2026-07-22, platform.kimi.ai docs +
live GET /v1/models with the provided key):

| Model | Context | Input $/Mtok | Output $/Mtok | Moonshot tier |
|---|---|---|---|---|
| kimi-k3 | 1,048,576 | 3.00 (0.30 cache hit) | 15.00 | flagship |
| kimi-k2.7-code | 262,144 | 0.95 (0.19 cache hit) | 4.00 | mid (dedicated coding, multimodal) |
| kimi-k2.6 | 262,144 | ~0.95 | ~4.00 | mid, vision+text |

**Tier decision (Roy, 2026-07-22): tier is capability, not vendor cost** —
same rule that put grok-4.5 ($2/$6) in top tier. kimi-k3 → `top_tier_models`
(flagship), kimi-k2.7-code → `mid_tier_models`. Catalog costs and provider
rates stay at Moonshot's actual list prices (K3 $3/$15 ≈ Sonnet-level rates;
K2.7 $0.95/$4) — billing margins come from the tier, prices from the vendor.
Coverage note: a model in neither tier list fails closed at rating, so this
listing is load-bearing, not cosmetic.

The account key's /v1/models lists only kimi-k2.7-code and kimi-k2.6 (k3 not
confirmed reachable — see blocker). Moonshot API is OpenAI-compatible at
https://api.moonshot.ai/v1, Bearer auth — same integration shape as xAI.

## Changes

Luna (submodule → 0.44.000, MINOR: new provider):
- `luna/llm/providers/moonshot.py` — MoonshotProvider(OpenAIProvider), default
  base https://api.moonshot.ai/v1; exported in providers/__init__.
- `luna/llm/router.py` — "moonshot" in _KEYED_PROVIDERS + _make_provider.
- `luna/config/schema.py` — moonshot_api_key / moonshot_base_url env fields;
  "moonshot" in configured_providers candidates.
- `luna/config/defaults/models_catalog.yaml` — kimi-k3 (alias: kimi) and
  kimi-k2.7-code (alias: kimi-code) entries.

luna-service:
- `cloud/gateway/registry.py` — SEED_SERVICES + KNOWN_SERVICES row "moonshot"
  (upstream https://api.moonshot.ai/v1, Bearer, provision_by_default).
- `cloud/gateway/model_registry.py` — kimi-k3 + kimi-k2.7-code catalog rows.
- `cloud/gateway/route_catalog.py` — moonshot.chat billed row + free /models.
- `cloud/gateway/adapters.py` — moonshot.chat → OpenAIChatCollector (Kimi's
  completion_tokens includes reasoning output, unlike xAI); added to
  _OPENAI_CHAT_COMPAT.
- `cloud/api/gateway_proxy.py` — "moonshot" model-gated.
- `cloud/billing/provider_rates_v1.py` — 6 rate rows (input/output/cached per
  model). NOTE: prod already has provider cost version 1 seeded — these rows
  only reach fresh installs. Prod needs a v2 draft+publish via the billing
  admin API before Kimi usage is rated (unrated dimensions under-bill, they
  don't block).

## Status

- [x] Code + tests (cloud suite 717 passed; luna provider/router/catalog
      tests 72 passed; 49 luna failures pre-existing, verified via stash)
- [x] Prod rollout (2026-07-22 evening): seeds live via deploy-hook deploy of
      d1cfb6d; pooled key added (gateway_keys 8b846ee2); provider cost v5
      published (= v4 + 6 kimi rates, diff verified); commercial pricing v5
      published (kimi-k3 top tier, kimi-k2.7-code mid, coverage clean); image
      0.44.000 set main; canary vaselin-pa healthy; migrate-all → 34/34
      machines on 0.44.000; env backfill for LUNA_MOONSHOT_API_KEY.
- [x] Proxy path verified end-to-end: /proxy/moonshot/chat/completions with a
      machine token reaches Moonshot and returns Moonshot's own error.
- [x] Balance funded (2026-07-22 late: $105 on the org after the first top-up
      went to the wrong account); /v1/models now serves kimi-k3 as well.
- [x] LIVE verification: kimi-k3 and kimi-k2.7-code completions succeed via
      /proxy/moonshot with a machine token; billing rated both
      (usage/breakdown by=model → kimi-k3 3 credits, kimi-k2.7-code 2).
- [x] 2026-07-23: chat path fix — reasoning turns crashed with "Unknown
      provider: moonshot" (pydantic-ai registry has no moonshot key; the
      string fall-through in `_pydantic_model_object` hit it — same class as
      the 2026-07-17 gemini bug; Luna's own ModelRouter was fine, which is
      why direct proxy tests passed). Fixed in luna 0.44.002 (af74d01):
      moonshot routes through OpenAIChatModel like xai. Fleet rolled to
      0.44.002 (34/34 + test agent), canary vaselin-pa healthy, end-to-end
      verified: kimi-k3 chat turn on a test agent answered "I'm Kimi,
      developed by Moonshot AI". This roll also delivered the 0.44.001 UI
      picker ranks.
- [ ] Follow-up: replace provisional kimi picker ranks with real Luna
      Benchmark scores when a run exists.
