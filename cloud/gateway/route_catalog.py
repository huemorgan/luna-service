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

# (service_slug, METHOD, normalized path) -> RouteClass. A trailing "*"
# matches exactly one extra path segment (e.g. GET /v1/models/{id}).
_CATALOG: dict[tuple[str, str, str], RouteClass] = {
    ("anthropic", "POST", "/v1/messages"): _billed("anthropic.messages", "llm_call"),
    ("anthropic", "POST", "/v1/messages/count_tokens"): _FREE,
    ("anthropic", "GET", "/v1/models"): _FREE,
    ("anthropic", "GET", "/v1/models/*"): _FREE,
    ("openai", "POST", "/v1/chat/completions"): _billed("openai.chat", "llm_call"),
    ("openai", "POST", "/v1/embeddings"): _billed("openai.embeddings", "llm_call"),
    ("openai", "GET", "/v1/models"): _FREE,
    ("openai", "GET", "/v1/models/*"): _FREE,
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
    # Single-segment wildcard: /v1/models/claude-x → /v1/models/*
    head, _, tail = norm.rpartition("/")
    if head and tail:
        return _CATALOG.get((service_slug, method, f"{head}/*"))
    return None
