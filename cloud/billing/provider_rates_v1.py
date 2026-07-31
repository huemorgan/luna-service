"""Provider-cost version 1 — reviewed, reproducible rate data (039/001).

This checked-in file is the ONLY source for provider-cost seeding. The
mutable `GatewayModel.input_cost/output_cost` floats are catalog metadata and
are ignored by every billing path.

Units: exact rational micro-USD per native unit, as (numerator, denominator).
Handy identity: $N per 1M tokens == N micro-USD per token, so a $3.00/Mtok
list price is exactly (3, 1) and $0.15/Mtok is (3, 20).

Quality is `estimated` until reconciled against a real provider invoice
(039/004 exit criteria moved that reconciliation to 039/010).
"""

RETRIEVED_AT = "2026-07-15"

# (provider, sku, dimension, unit, rate_numerator, rate_denominator, source_url)
PROVIDER_RATES_V1: list[tuple[str, str, str, str, int, int, str]] = [
    # Anthropic — https://docs.anthropic.com/en/docs/about-claude/pricing
    ("anthropic", "claude-opus-4-6", "input_tokens", "token", 5, 1,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-opus-4-6", "output_tokens", "token", 25, 1,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-sonnet-4-5-20250929", "input_tokens", "token", 3, 1,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-sonnet-4-5-20250929", "output_tokens", "token", 15, 1,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-sonnet-4-20250514", "input_tokens", "token", 3, 1,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-sonnet-4-20250514", "output_tokens", "token", 15, 1,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-haiku-4-5-20251001", "input_tokens", "token", 1, 1,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-haiku-4-5-20251001", "output_tokens", "token", 5, 1,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    # Anthropic prompt caching (039/004): reads = 0.1× input, 5m writes =
    # 1.25× input. Billed as their own dimensions — the adapters report
    # uncached input, cache reads and cache writes disjointly.
    ("anthropic", "claude-opus-4-6", "cache_read_input_tokens", "token", 1, 2,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-opus-4-6", "cache_creation_input_tokens", "token", 25, 4,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-sonnet-4-5-20250929", "cache_read_input_tokens", "token", 3, 10,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-sonnet-4-5-20250929", "cache_creation_input_tokens", "token", 15, 4,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-sonnet-4-20250514", "cache_read_input_tokens", "token", 3, 10,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-sonnet-4-20250514", "cache_creation_input_tokens", "token", 15, 4,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-haiku-4-5-20251001", "cache_read_input_tokens", "token", 1, 10,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    ("anthropic", "claude-haiku-4-5-20251001", "cache_creation_input_tokens", "token", 5, 4,
     "https://docs.anthropic.com/en/docs/about-claude/pricing"),
    # OpenAI — https://platform.openai.com/docs/pricing
    ("openai", "gpt-4o", "input_tokens", "token", 5, 2,           # $2.50/Mtok
     "https://platform.openai.com/docs/pricing"),
    ("openai", "gpt-4o", "output_tokens", "token", 10, 1,
     "https://platform.openai.com/docs/pricing"),
    ("openai", "gpt-4o-mini", "input_tokens", "token", 3, 20,     # $0.15/Mtok
     "https://platform.openai.com/docs/pricing"),
    ("openai", "gpt-4o-mini", "output_tokens", "token", 3, 5,     # $0.60/Mtok
     "https://platform.openai.com/docs/pricing"),
    # OpenAI cached input (039/004): prompt_tokens_details.cached_tokens,
    # billed at the provider's cached-input rate (0.5× list input).
    ("openai", "gpt-4o", "cached_input_tokens", "token", 5, 4,    # $1.25/Mtok
     "https://platform.openai.com/docs/pricing"),
    ("openai", "gpt-4o-mini", "cached_input_tokens", "token", 3, 40,  # $0.075/Mtok
     "https://platform.openai.com/docs/pricing"),
    # GPT-5.5 — retrieved 2026-07-16. Prompts >272k tokens are surcharged
    # (2× input, 1.5× output) but the usage object doesn't split them out —
    # billed at the base rate (known undercount on rare huge prompts).
    ("openai", "gpt-5.5", "input_tokens", "token", 5, 1,
     "https://developers.openai.com/api/docs/models/gpt-5.5"),
    ("openai", "gpt-5.5", "output_tokens", "token", 30, 1,
     "https://developers.openai.com/api/docs/models/gpt-5.5"),
    ("openai", "gpt-5.5", "cached_input_tokens", "token", 1, 2,   # $0.50/Mtok
     "https://developers.openai.com/api/docs/models/gpt-5.5"),
    ("openai", "text-embedding-3-small", "input_tokens", "token", 1, 50,   # $0.02/Mtok
     "https://platform.openai.com/docs/pricing"),
    ("openai", "text-embedding-3-large", "input_tokens", "token", 13, 100,  # $0.13/Mtok
     "https://platform.openai.com/docs/pricing"),
    # xAI (Grok) — live GET /v1/language-models, 2026-07-15. The API's price
    # unit is $0.0001 per 1M tokens; converted here to micro-USD per token.
    # Long-context (>200k prompt) surcharge tiers exist but the usage object
    # doesn't split them out — billed at the base rate (known undercount on
    # rare huge prompts).
    ("xai", "grok-4.5", "input_tokens", "token", 2, 1,            # $2.00/Mtok
     "https://docs.x.ai/docs/models"),
    ("xai", "grok-4.5", "output_tokens", "token", 6, 1,           # $6.00/Mtok
     "https://docs.x.ai/docs/models"),
    ("xai", "grok-4.5", "cached_input_tokens", "token", 1, 2,     # $0.50/Mtok
     "https://docs.x.ai/docs/models"),
    ("xai", "grok-4.3", "input_tokens", "token", 5, 4,            # $1.25/Mtok
     "https://docs.x.ai/docs/models"),
    ("xai", "grok-4.3", "output_tokens", "token", 5, 2,           # $2.50/Mtok
     "https://docs.x.ai/docs/models"),
    ("xai", "grok-4.3", "cached_input_tokens", "token", 1, 5,     # $0.20/Mtok
     "https://docs.x.ai/docs/models"),
    ("xai", "grok-build-0.1", "input_tokens", "token", 1, 1,      # $1.00/Mtok
     "https://docs.x.ai/docs/models"),
    ("xai", "grok-build-0.1", "output_tokens", "token", 2, 1,     # $2.00/Mtok
     "https://docs.x.ai/docs/models"),
    ("xai", "grok-build-0.1", "cached_input_tokens", "token", 1, 5,  # $0.20/Mtok
     "https://docs.x.ai/docs/models"),
    # Moonshot AI (Kimi) — retrieved 2026-07-22. OpenAI-compat usage;
    # cached input reported as prompt_tokens_details.cached_tokens.
    ("moonshot", "kimi-k3", "input_tokens", "token", 3, 1,
     "https://platform.kimi.ai/docs/pricing/chat-k3"),
    ("moonshot", "kimi-k3", "output_tokens", "token", 15, 1,
     "https://platform.kimi.ai/docs/pricing/chat-k3"),
    ("moonshot", "kimi-k3", "cached_input_tokens", "token", 3, 10,   # $0.30/Mtok
     "https://platform.kimi.ai/docs/pricing/chat-k3"),
    ("moonshot", "kimi-k2.7-code", "input_tokens", "token", 19, 20,  # $0.95/Mtok
     "https://platform.kimi.ai/docs/pricing/chat-k27-code"),
    ("moonshot", "kimi-k2.7-code", "output_tokens", "token", 4, 1,
     "https://platform.kimi.ai/docs/pricing/chat-k27-code"),
    ("moonshot", "kimi-k2.7-code", "cached_input_tokens", "token", 19, 100,  # $0.19/Mtok
     "https://platform.kimi.ai/docs/pricing/chat-k27-code"),
    # kimi-k2.6 ("Agent Ops") — retrieved 2026-07-31 (063).
    ("moonshot", "kimi-k2.6", "input_tokens", "token", 19, 20,  # $0.95/Mtok
     "https://platform.kimi.ai/docs/pricing/chat-k26"),
    ("moonshot", "kimi-k2.6", "output_tokens", "token", 4, 1,
     "https://platform.kimi.ai/docs/pricing/chat-k26"),
    ("moonshot", "kimi-k2.6", "cached_input_tokens", "token", 3, 20,  # $0.15/Mtok
     "https://platform.kimi.ai/docs/pricing/chat-k26"),
    # Image generation (041). Gemini bills output images as IMAGE-modality
    # candidate tokens (flash: 1290 tok ≈ $0.039/image; 3-pro: 1120 tok ≈
    # $0.134 at 1K/2K, 2000 tok ≈ $0.24 at 4K); text + thinking output is a
    # separate cheaper dimension.
    ("gemini", "gemini-3-pro-image", "input_tokens", "token", 2, 1,        # $2.00/Mtok
     "https://ai.google.dev/gemini-api/docs/pricing"),
    ("gemini", "gemini-3-pro-image", "output_image_tokens", "token", 120, 1,
     "https://ai.google.dev/gemini-api/docs/pricing"),
    ("gemini", "gemini-3-pro-image", "output_text_tokens", "token", 12, 1,
     "https://ai.google.dev/gemini-api/docs/pricing"),
    ("gemini", "gemini-2.5-flash-image", "input_tokens", "token", 3, 10,   # $0.30/Mtok
     "https://ai.google.dev/gemini-api/docs/pricing"),
    ("gemini", "gemini-2.5-flash-image", "output_image_tokens", "token", 30, 1,
     "https://ai.google.dev/gemini-api/docs/pricing"),
    ("gemini", "gemini-2.5-flash-image", "output_text_tokens", "token", 5, 2,  # $2.50/Mtok
     "https://ai.google.dev/gemini-api/docs/pricing"),
    # OpenAI images API splits input into text/image dimensions; output tokens
    # are image tokens. gpt-image-1 is deprecated (retires 2026-10-23) — 1.5
    # and mini are pre-priced so a plugin bump needs no new cost version.
    ("openai", "gpt-image-1", "input_text_tokens", "token", 5, 1,
     "https://developers.openai.com/api/docs/models/gpt-image-1"),
    ("openai", "gpt-image-1", "input_image_tokens", "token", 10, 1,
     "https://developers.openai.com/api/docs/models/gpt-image-1"),
    ("openai", "gpt-image-1", "output_tokens", "token", 40, 1,
     "https://developers.openai.com/api/docs/models/gpt-image-1"),
    ("openai", "gpt-image-1.5", "input_text_tokens", "token", 5, 1,
     "https://developers.openai.com/api/docs/pricing"),
    ("openai", "gpt-image-1.5", "input_image_tokens", "token", 8, 1,
     "https://developers.openai.com/api/docs/pricing"),
    ("openai", "gpt-image-1.5", "output_tokens", "token", 32, 1,
     "https://developers.openai.com/api/docs/pricing"),
    ("openai", "gpt-image-1-mini", "input_text_tokens", "token", 2, 1,
     "https://developers.openai.com/api/docs/pricing"),
    ("openai", "gpt-image-1-mini", "input_image_tokens", "token", 5, 2,   # $2.50/Mtok
     "https://developers.openai.com/api/docs/pricing"),
    ("openai", "gpt-image-1-mini", "output_tokens", "token", 8, 1,
     "https://developers.openai.com/api/docs/pricing"),
    # Realtime voice — flat per-session vendor ESTIMATE, not a list price.
    # Audio flows browser ⇄ OpenAI over WebRTC on the minted ephemeral key,
    # so the gateway never sees the minutes; the mint is the billable unit.
    # Estimate ≈ a typical 5-10 min conversation at gpt-realtime audio token
    # rates ($32/$64 per Mtok in/out). Reconcile against real invoices and
    # republish if sessions run materially longer.
    ("openai", "gpt-realtime-2.1", "sessions", "session", 500_000, 1,
     "https://developers.openai.com/api/docs/pricing"),
    ("openai", "gpt-4o-realtime-preview", "sessions", "session", 500_000, 1,
     "https://developers.openai.com/api/docs/pricing"),
    ("openai", "gpt-realtime-2.1-mini", "sessions", "session", 150_000, 1,
     "https://developers.openai.com/api/docs/pricing"),
    ("openai", "gpt-4o-mini-realtime-preview", "sessions", "session", 150_000, 1,
     "https://developers.openai.com/api/docs/pricing"),
]
