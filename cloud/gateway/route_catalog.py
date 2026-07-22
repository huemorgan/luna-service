"""Managed-gateway route classification — deny by default (039/004).

Every managed (platform-keyed) request is classified by
``(service_slug, method, normalized path)`` before any upstream contact.
A route is either:

- **billed** — maps to exactly one usage adapter and one SKU key from the
  active commercial pricing version;
- **free** — explicitly allowed metadata traffic (model listings, token
  counting) that never spends provider money worth metering;
- **unknown** — everything else. Unknown routes are `sku_unpriced`: blocked
  before upstream in enforce mode, recorded as a would-block decision in
  observe/shadow.

BYOK passthrough traffic is never classified — it is never billed.
Phase 005 adds non-LLM services through this table instead of duplicating
enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteClass:
    kind: str            # "billed" | "free"
    adapter: str | None  # adapter name for billed routes
    sku: str | None      # SKU key in the commercial config for billed routes


def _billed(adapter: str, sku: str) -> RouteClass:
    return RouteClass(kind="billed", adapter=adapter, sku=sku)


_FREE = RouteClass(kind="free", adapter=None, sku=None)

# (service_slug, METHOD, normalized path) -> RouteClass. A "*" segment
# matches exactly one path segment, in any position (e.g. GET /v1/models/{id},
# POST /trigger_instances/{slug}/upsert). At most one "*" per entry.
_CATALOG: dict[tuple[str, str, str], RouteClass] = {
    ("anthropic", "POST", "/v1/messages"): _billed("anthropic.messages", "llm_call"),
    ("anthropic", "POST", "/v1/messages/count_tokens"): _FREE,
    ("anthropic", "GET", "/v1/models"): _FREE,
    ("anthropic", "GET", "/v1/models/*"): _FREE,
    ("openai", "POST", "/v1/chat/completions"): _billed("openai.chat", "llm_call"),
    ("openai", "POST", "/v1/embeddings"): _billed("openai.embeddings", "llm_call"),
    ("openai", "GET", "/v1/models"): _FREE,
    ("openai", "GET", "/v1/models/*"): _FREE,
    # OpenAI-compatible SDKs pointed at /proxy/{slug} append BARE paths — the
    # /v1 lives in the service's upstream_url. Real Luna traffic arrives as
    # /chat/completions, so the bare variants are the ones that actually match;
    # the /v1-prefixed rows above are kept for direct callers.
    ("openai", "POST", "/chat/completions"): _billed("openai.chat", "llm_call"),
    ("openai", "POST", "/embeddings"): _billed("openai.embeddings", "llm_call"),
    ("openai", "GET", "/models"): _FREE,
    ("openai", "GET", "/models/*"): _FREE,
    ("xai", "POST", "/chat/completions"): _billed("xai.chat", "llm_call"),
    ("xai", "GET", "/models"): _FREE,
    ("xai", "GET", "/models/*"): _FREE,
    ("xai", "GET", "/language-models"): _FREE,
    ("xai", "GET", "/language-models/*"): _FREE,
    # Image generation (041). Gemini rows are explicit per model — a /models/*
    # wildcard would also swallow :countTokens / :streamGenerateContent and
    # arbitrary text models, which must stay deny-by-default. The model is in
    # the PATH, not the body (adapters.extract_model handles that).
    ("gemini", "POST", "/models/gemini-3-pro-image:generateContent"):
        _billed("gemini.generate", "image_gen"),
    ("gemini", "POST", "/models/gemini-2.5-flash-image:generateContent"):
        _billed("gemini.generate", "image_gen"),
    ("gemini", "GET", "/models"): _FREE,
    ("gemini", "GET", "/models/*"): _FREE,
    # 050: Gemini reasoning rides Google's OpenAI-compat surface — the agent
    # points an OpenAI client at /proxy/gemini/openai, so the bare paths are
    # /openai/... . Usage is OpenAI-shaped (gemini.chat collector).
    ("gemini", "POST", "/openai/chat/completions"): _billed("gemini.chat", "llm_call"),
    ("gemini", "GET", "/openai/models"): _FREE,
    ("gemini", "GET", "/openai/models/*"): _FREE,
    # /images/edits is multipart form-data — extract_model scans the form.
    ("openai", "POST", "/images/generations"): _billed("openai.images", "image_gen"),
    ("openai", "POST", "/images/edits"): _billed("openai.images", "image_gen"),
    ("openai", "POST", "/v1/images/generations"): _billed("openai.images", "image_gen"),
    ("openai", "POST", "/v1/images/edits"): _billed("openai.images", "image_gen"),
    # Composio (043): connector management + tool execution ride the proxy;
    # all free — Composio is flat-rate to Luna ("Included with Luna Cloud").
    # Per-execute metering is deferred until enforcement can rate model-less
    # per-request SKUs. Path list mirrors plugin-connectors' composio driver.
    ("composio", "GET", "/toolkits"): _FREE,
    ("composio", "GET", "/toolkits/*"): _FREE,
    ("composio", "GET", "/tools"): _FREE,
    ("composio", "POST", "/tools/execute/*"): _FREE,
    ("composio", "POST", "/auth_configs"): _FREE,
    ("composio", "POST", "/connected_accounts"): _FREE,
    ("composio", "POST", "/connected_accounts/link"): _FREE,
    ("composio", "GET", "/connected_accounts/*"): _FREE,
    ("composio", "DELETE", "/connected_accounts/*"): _FREE,
    ("composio", "GET", "/triggers_types"): _FREE,
    ("composio", "POST", "/trigger_instances/*/upsert"): _FREE,
    ("composio", "DELETE", "/trigger_instances/manage/*"): _FREE,
    # Tavily web search (plugin-web-access). Free until search_request SKU is
    # priced/enabled — same interim posture as Composio. Without this row,
    # enforce mode fails closed as sku_unpriced before upstream (and before
    # the tenant-token body strip), so managed search never leaves the gateway.
    ("tavily", "POST", "/search"): _FREE,
}


def normalize_path(path: str) -> str:
    """Normalize the proxied sub-path: one leading slash, collapsed duplicate
    slashes, no trailing slash (except the root itself). Case is preserved —
    provider paths are case-sensitive."""
    parts = [seg for seg in path.split("/") if seg]
    return "/" + "/".join(parts)


def classify(service_slug: str, method: str, path: str) -> RouteClass | None:
    """Classify a managed request. None = unknown route (fails closed as
    `sku_unpriced` in enforce mode)."""
    norm = normalize_path(path)
    method = method.upper()
    exact = _CATALOG.get((service_slug, method, norm))
    if exact is not None:
        return exact
    # Single-segment wildcard: exactly one segment replaced by "*", tried
    # tail-first (/v1/models/claude-x → /v1/models/*, then
    # /trigger_instances/GMAIL_NEW_MSG/upsert → /trigger_instances/*/upsert).
    segments = norm.split("/")[1:]
    for i in reversed(range(len(segments))):
        candidate = "/" + "/".join([*segments[:i], "*", *segments[i + 1:]])
        hit = _CATALOG.get((service_slug, method, candidate))
        if hit is not None:
            return hit
    return None
