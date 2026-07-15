# 041 — Image-generation billing (gemini + openai image routes)

## Correction to the premise

plugin-image-gen does **not** use fal.ai. Its three providers are:

| plugin provider | upstream | gateway service | proxied today? |
|---|---|---|---|
| gemini (nano-banana-pro = `gemini-3-pro-image`, nano-banana = `gemini-2.5-flash-image`) | `generativelanguage.googleapis.com/v1beta` | `gemini` (query:key, provisioned) | yes — unpriced |
| openai (`gpt-image-1`) | `api.openai.com/v1` | `openai` (provisioned) | yes — unpriced |
| flux (BFL `flux-pro-1.1[-ultra]`) | `api.bfl.ai` | **none** | no — BYO key only |

The prod `fal` service (enabled, provision_by_default, 1 key) is used by **nothing**
— no plugin, no agent code, zero recorded usage ever. Out of scope here; flagged
for a separate disable decision.

So "make image gen work + billed" = price the **gemini** and **openai image**
routes the plugin actually calls. BFL stays BYO (we hold no BFL key).

## Gaps in the billing pipeline

1. **No route entries**: `route_catalog.py` has nothing for `gemini`, and no
   `/images/*` for `openai` → unknown route → unbilled in log mode, blocked in
   enforce (canary account = enforce).
2. **Model extraction is JSON-body-only** (`body_json["model"]`):
   - gemini carries the model in the URL path (`/models/gemini-3-pro-image:generateContent`);
   - `POST /images/edits` is multipart form — no JSON body at all.
3. **No usage adapters** for gemini `usageMetadata` or the openai images
   `usage` object (with `input_tokens_details`).
4. **No rates / no SKU / no tier coverage** for image models.
5. **openai is model-catalog-gated** at the proxy (`_MODEL_GATED_PROVIDERS`):
   `gpt-image-1` must be an enabled `gateway_models` row or the proxy 404s
   before billing is even consulted. gemini is not gated.

## Changes (luna-service)

### 1. `cloud/gateway/route_catalog.py`
```
("gemini", "POST", "/models/gemini-3-pro-image:generateContent")   → billed("gemini.generate", "image_gen")
("gemini", "POST", "/models/gemini-2.5-flash-image:generateContent") → billed("gemini.generate", "image_gen")
("gemini", "GET",  "/models"), ("gemini", "GET", "/models/*")       → free
("openai", "POST", "/images/generations"), + "/v1/images/generations" → billed("openai.images", "image_gen")
("openai", "POST", "/images/edits"),       + "/v1/images/edits"       → billed("openai.images", "image_gen")
```
Explicit per-model gemini entries (not a wildcard): `/models/*` would also match
`:countTokens` / `:streamGenerateContent` / arbitrary text models; deny-by-default
stays intact for those.

### 2. `cloud/gateway/adapters.py`
- `extract_model(adapter, body_json, path, content_type, body)` — the seam
  `enforcement.prepare()` calls instead of inlining `body_json["model"]`:
  - default: `body_json["model"]` (unchanged behavior);
  - `gemini.generate`: last path segment before `:` → `gemini-3-pro-image`;
  - `openai.images`: JSON `model`, else multipart scan for the `model` field.
- `GeminiGenerateCollector` — parses `usageMetadata`; dimensions:
  - `input_tokens`   = `promptTokenCount`
  - `output_image_tokens` = Σ `candidatesTokensDetails[modality=IMAGE]`
  - `output_text_tokens`  = (`candidatesTokenCount` − image) + `thoughtsTokenCount`
  Inline-image responses are MBs of base64 → override the oversized-body scan to
  look for `usageMetadata` (base scans `usage`). Model/id from `modelVersion` / `responseId`.
- `OpenAIImagesCollector` — parses `usage`; dimensions:
  - `input_text_tokens`  = `input_tokens_details.text_tokens`
  - `input_image_tokens` = `input_tokens_details.image_tokens`
  - `output_tokens`      = `output_tokens` (image output)
  b64_json responses are MBs → default oversized `usage` scan already works.
- `estimate_dimensions`: gemini.generate → `{input, output_image_tokens: 2000}`
  (4K worst case ≈ $0.24 hold); openai.images → `{input, output_tokens: 4160·n}`
  (high-quality 1024² worst case ≈ $0.17/image).

### 3. `cloud/gateway/enforcement.py`
Replace the inline model read with `usage_adapters.extract_model(...)`.

### 4. Pricing data
`cloud/billing/provider_rates_v1.py` (+ prod provider-cost **v3** via admin API —
full-list POST, publish with reason). Rates in micro-USD/token, exact rationals:

| provider | sku | dimension | $/1M | (num, den) |
|---|---|---|---|---|
| gemini | gemini-3-pro-image | input_tokens | 2.00 | (2, 1) |
| gemini | gemini-3-pro-image | output_image_tokens | 120.00 | (120, 1) |
| gemini | gemini-3-pro-image | output_text_tokens | 12.00 | (12, 1) |
| gemini | gemini-2.5-flash-image | input_tokens | 0.30 | (3, 10) |
| gemini | gemini-2.5-flash-image | output_image_tokens | 30.00 | (30, 1) |
| gemini | gemini-2.5-flash-image | output_text_tokens | 2.50 | (5, 2) |
| openai | gpt-image-1 | input_text_tokens | 5.00 | (5, 1) |
| openai | gpt-image-1 | input_image_tokens | 10.00 | (10, 1) |
| openai | gpt-image-1 | output_tokens | 40.00 | (40, 1) |
| openai | gpt-image-1.5 | input_text_tokens | 5.00 | (5, 1) |
| openai | gpt-image-1.5 | input_image_tokens | 8.00 | (8, 1) |
| openai | gpt-image-1.5 | output_tokens | 32.00 | (32, 1) |
| openai | gpt-image-1-mini | input_text_tokens | 2.00 | (2, 1) |
| openai | gpt-image-1-mini | input_image_tokens | 2.50 | (5, 2) |
| openai | gpt-image-1-mini | output_tokens | 8.00 | (8, 1) |

Sources: ai.google.dev/gemini-api/docs/pricing, developers.openai.com/api/docs
(gpt-image-1 is **deprecated**, retires 2026-10-23 — 1.5/mini rates included now
so the plugin can migrate without a new cost version).
Reference points: nano-banana ≈ $0.039/image, nano-banana-pro ≈ $0.134 (1K/2K)
/ $0.24 (4K), gpt-image-1 high 1024² ≈ $0.17.

### 5. `cloud/billing/seed.py` (+ prod commercial **v3** clone→PUT→publish)
- `mid_tier_models` += `gemini-3-pro-image`, `gemini-2.5-flash-image`,
  `gpt-image-1`, `gpt-image-1.5`, `gpt-image-1-mini` (margin: existing
  `llm_constants.agent.mid` = 10 000 µ$ = 1 credit per call).
- `skus` += `{"key": "image_gen", "service": "image", "formula":
  "vendor_plus_context_constant", "enabled": True}`.

### 6. Model catalog
- `_VALID_KINDS` += `"image"` (Luna's `ModelCatalogEntry.kinds` is a free
  string list — unknown kinds are ignored by `for_purpose`, verified).
- Prod: `POST /api/admin/gateway/models` `{provider: "openai", model:
  "gpt-image-1", kinds: ["image"]}` — required by the proxy's catalog wall.
  gemini models are not gated → no catalog rows needed (skip; avoids noise in
  LUNA_MODEL_CATALOG).

### 7. Tests (`cloud/tests/test_gateway_billing.py` et al.)
- route classification for the six new entries; deny stays for
  `gemini POST /models/gemini-3-pro-image:streamGenerateContent` etc.
- `extract_model`: gemini path, openai JSON, openai multipart, default JSON.
- `GeminiGenerateCollector`: normal JSON, oversized scan, text+image split,
  thoughts tokens.
- `OpenAIImagesCollector`: generations usage shape, details split.
- estimate shapes for both adapters.

## Rollout

1. Full test suite (unpiped), commit, push (auto-deploys via deploy_hook), poll deploy live.
2. `POST /api/admin/gateway/models` gpt-image-1 (kind image).
3. Provider-cost v3: GET v2 rates → append 15 image rates → POST full list →
   publish (reason).
4. Commercial v3: clone v2 → add image_gen SKU + 5 mid-tier models → PUT →
   publish (reason). Publish validation passes because gpt-image-1 is covered.
5. Live verify on canary (vaselin account, enforce): read agent machine token
   from Fly (never rotate), call
   `POST /proxy/gemini/models/gemini-2.5-flash-image:generateContent?key=<token>`
   and `POST /proxy/openai/images/generations` (gpt-image-1, low cost) —
   confirm 200, BillableEvent + RatedCharge rows, credits ≈ 5 (flash image:
   $0.039 + 1¢ margin) and ≈ 3–18 (gpt-image-1 by quality), wallet settles.
   Check `unrated_dimensions` is empty on both (validates dimension naming
   against real provider usage shapes).
6. If gemini's real `usageMetadata` shape differs (e.g. no
   `candidatesTokensDetails`), fix the collector before announcing done —
   unrated dimensions are visible in the charge snapshot.

## Out of scope / flagged

- **fal service**: unused by everything; recommend disable (needs an admin
  service-update endpoint or DB change — separate decision).
- **BFL/flux**: no gateway service or platform key; stays BYO. Adding it means
  a new service + key + async submit/poll billing (result cost only appears on
  the poll, not the submit) — separate plan if wanted.
- **Plugin migration off deprecated gpt-image-1** (luna-plugins repo) before
  2026-10-23; rates for 1.5/mini already published by this plan.
