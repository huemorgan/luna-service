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

RETRIEVED_AT = "2026-07-13"

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
    # OpenAI — https://platform.openai.com/docs/pricing
    ("openai", "gpt-4o", "input_tokens", "token", 5, 2,           # $2.50/Mtok
     "https://platform.openai.com/docs/pricing"),
    ("openai", "gpt-4o", "output_tokens", "token", 10, 1,
     "https://platform.openai.com/docs/pricing"),
    ("openai", "gpt-4o-mini", "input_tokens", "token", 3, 20,     # $0.15/Mtok
     "https://platform.openai.com/docs/pricing"),
    ("openai", "gpt-4o-mini", "output_tokens", "token", 3, 5,     # $0.60/Mtok
     "https://platform.openai.com/docs/pricing"),
    ("openai", "text-embedding-3-small", "input_tokens", "token", 1, 50,   # $0.02/Mtok
     "https://platform.openai.com/docs/pricing"),
    ("openai", "text-embedding-3-large", "input_tokens", "token", 13, 100,  # $0.13/Mtok
     "https://platform.openai.com/docs/pricing"),
]
