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

**Tier verdict: the "high and mid" assumption is one tier off.** Kimi K3
($3/$15) prices exactly at our MID tier (= Sonnet 4.5); K2.7 Code ($0.95/$4)
prices at our LOW tier (≈ Haiku 4.5 $1/$5). No Kimi model reaches our high
tier (Opus $5/$25, GPT-5.5 $5/$30). Rows are priced at Moonshot's actual list
prices — catalog costs and billing rates must reflect reality, not the
intended tier.

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
- [ ] BLOCKED on Roy: Moonshot account org-3e4ad1c9ed9f4f4bbda6b8794e738cb9 is
      suspended — "insufficient balance". Recharge at platform.moonshot.ai,
      then: verify kimi-k3 is servable on the account tier.
- [ ] Prod rollout after recharge: add gateway service row + pooled key +
      model rows (admin API or redeploy for seeds), publish provider cost v2,
      build luna 0.44.000 image, roll fleet.
