"""Service registry — seeding, lookup, auth-style parsing."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.db.models import GatewayService

# Seeded once at startup; everything else is data entered via the admin UI.
SEED_SERVICES: list[dict] = [
    {
        "slug": "anthropic",
        "display_name": "Anthropic",
        "upstream_url": "https://api.anthropic.com",
        "auth_style": "header:x-api-key",
        "enabled": True,
        "provision_by_default": True,
    },
    {
        "slug": "openai",
        "display_name": "OpenAI",
        # The OpenAI SDK's default base is .../v1, so with a base_url override
        # it appends bare paths (/embeddings, /chat/completions) — the /v1
        # must live here.
        "upstream_url": "https://api.openai.com/v1",
        "auth_style": "header:Authorization:Bearer",
        "enabled": True,
        "provision_by_default": True,
    },
    {
        # Luna has no LUNA_TAVILY_BASE_URL support yet (007.001 pending) —
        # registered but not provisioned through the proxy.
        "slug": "tavily",
        "display_name": "Tavily",
        "upstream_url": "https://api.tavily.com",
        "auth_style": "header:Authorization:Bearer",
        "enabled": True,
        "provision_by_default": False,
    },
    {
        # Browser Use Cloud — managed AI browser automation. v3 REST API lives
        # under /api/v3, so the gateway supplies that prefix (same trick as
        # OpenAI's /v1). Auth is a bare custom header (no scheme); keys are bu_…
        "slug": "browser-use",
        "display_name": "Browser Use",
        "upstream_url": "https://api.browser-use.com/api/v3",
        "auth_style": "header:X-Browser-Use-API-Key",
        "enabled": True,
        "provision_by_default": True,
    },
    {
        # Composio's REST API lives under /api/v3 — when Luna calls
        # LUNA_COMPOSIO_BASE_URL/toolkits in proxy mode the gateway has to
        # supply the /api/v3 prefix itself (same trick as OpenAI's /v1 above).
        "slug": "composio",
        "display_name": "Composio",
        "upstream_url": "https://backend.composio.dev/api/v3",
        "auth_style": "header:x-api-key",
        "luna_credential_name": "plugin_connectors.composio.api_key",  # legacy name
        "enabled": False,
        "provision_by_default": False,
    },
]


def default_names(slug: str) -> dict[str, str]:
    upper = slug.upper().replace("-", "_")
    return {
        "luna_credential_name": f"{slug}_api_key",
        "luna_env_key_var": f"LUNA_{upper}_API_KEY",
        "luna_env_base_url_var": f"LUNA_{upper}_BASE_URL",
    }


async def seed_services(db: AsyncSession) -> None:
    """Insert missing seed rows. Never overwrites admin edits."""
    existing = set((await db.execute(select(GatewayService.slug))).scalars().all())
    for spec in SEED_SERVICES:
        if spec["slug"] in existing:
            continue
        row = {**default_names(spec["slug"]), **spec}
        db.add(GatewayService(**row))
    await db.flush()


async def get_service(db: AsyncSession, slug: str) -> GatewayService | None:
    return (await db.execute(
        select(GatewayService).where(GatewayService.slug == slug)
    )).scalar_one_or_none()


@dataclass
class AuthStyle:
    header: str          # header name, or (when location=="query") the query-param name
    scheme: str | None   # e.g. "Bearer" or None
    location: str = "header"  # "header" | "query"

    @property
    def is_query(self) -> bool:
        return self.location == "query"

    def render(self, key: str) -> str:
        return f"{self.scheme} {key}" if self.scheme else key

    def extract(self, header_value: str) -> str:
        """Pull the bare credential out of an incoming header value."""
        if self.scheme and header_value.lower().startswith(self.scheme.lower() + " "):
            return header_value[len(self.scheme) + 1:].strip()
        return header_value.strip()


def parse_auth_style(style: str) -> AuthStyle:
    """Parse an auth_style string.

    - ``header:x-api-key``              → header ``x-api-key``, no scheme
    - ``header:Authorization:Bearer``  → header ``Authorization``, scheme ``Bearer``
    - ``query:api_key``                → key passed as the ``api_key`` query param
      (plan 026 — for key-in-query APIs like GIPHY)
    """
    parts = style.split(":")
    if len(parts) < 2:
        raise ValueError(f"Unsupported auth_style: {style}")
    if parts[0] == "header":
        return AuthStyle(header=parts[1], scheme=parts[2] if len(parts) > 2 else None)
    if parts[0] == "query":
        return AuthStyle(header=parts[1], scheme=None, location="query")
    raise ValueError(f"Unsupported auth_style: {style}")


# ── Smart key suggestion (plan 026) ──────────────────────────────────────────
#
# Pre-fill a GatewayService proposal per plugin so an admin clicks "use
# suggestion" instead of typing upstream URLs. Keyed by the service slug derived
# from the plugin name (strip the "plugin-" prefix). Grows as plugins are added.
#   slug -> (upstream_url, auth_style, display_name)
KNOWN_SERVICES: dict[str, tuple[str, str, str]] = {
    "funnelfighters": ("https://api.funnelfighters.io", "header:Authorization:Bearer", "FunnelFighters"),
    "monday":         ("https://api.monday.com/v2",      "header:Authorization",        "monday.com"),
    "render":         ("https://api.render.com/v1",       "header:Authorization:Bearer", "Render"),
    "giphy":          ("https://api.giphy.com/v1",        "query:api_key",               "GIPHY"),
    "browser-use":    ("https://api.browser-use.com/api/v3", "header:X-Browser-Use-API-Key", "Browser Use"),
    "composio":       ("https://backend.composio.dev/api/v3", "header:x-api-key",         "Composio"),
    "tavily":         ("https://api.tavily.com",           "header:Authorization:Bearer", "Tavily"),
    "openai":         ("https://api.openai.com/v1",         "header:Authorization:Bearer", "OpenAI"),
    "anthropic":      ("https://api.anthropic.com",         "header:x-api-key",            "Anthropic"),
}


# Plugins that consume an EXTERNAL pooled key, and which gateway service each one
# uses. A plugin absent from this map needs no external key (leaf plugins like
# interview / charts / recall / web-access) — the admin UI hides the key control
# for them entirely, and connector plugins only offer their own service (e.g.
# plugin-browser → browser-use, never Anthropic). Keyed by normalised plugin name
# because the service slug isn't always the suffix (plugin-browser → browser-use).
PLUGIN_KEY_SERVICES: dict[str, str] = {
    "plugin-browser": "browser-use",
    "plugin-giphy": "giphy",
    "plugin-monday": "monday",
    "plugin-render": "render",
    "plugin-funnelfighters": "funnelfighters",
    "plugin-connectors": "composio",
    "plugin-cloudflare": "cloudflare",
}


def key_service_for_plugin(plugin_name: str) -> str | None:
    """The gateway service a plugin needs a key for, or None if it needs none."""
    return PLUGIN_KEY_SERVICES.get((plugin_name or "").strip().lower().replace("_", "-"))


def service_slug_for_plugin(plugin_name: str) -> str:
    """Derive the gateway service slug from a plugin name ('plugin-monday' → 'monday')."""
    norm = (plugin_name or "").strip().lower().replace("_", "-")
    if norm in PLUGIN_KEY_SERVICES:
        return PLUGIN_KEY_SERVICES[norm]
    return plugin_name.strip().lower().removeprefix("plugin-")


def suggest_service(plugin_name: str, *, display_name: str | None = None) -> dict:
    """Pre-filled GatewayService proposal for a plugin.

    Known slug → correct one-click suggestion. Unknown slug → default names +
    blank upstream/auth_style, flagged ``needs_review`` for the admin to finish.
    """
    slug = service_slug_for_plugin(plugin_name)
    names = default_names(slug)
    if slug in KNOWN_SERVICES:
        upstream, auth_style, disp = KNOWN_SERVICES[slug]
        return {
            "slug": slug,
            "display_name": disp,
            "upstream_url": upstream,
            "auth_style": auth_style,
            "luna_env_key_var": names["luna_env_key_var"],
            "luna_env_base_url_var": names["luna_env_base_url_var"],
            "needs_review": False,
        }
    return {
        "slug": slug,
        "display_name": display_name or slug.replace("-", " ").title(),
        "upstream_url": "",
        "auth_style": "",
        "luna_env_key_var": names["luna_env_key_var"],
        "luna_env_base_url_var": names["luna_env_base_url_var"],
        "needs_review": True,
    }
