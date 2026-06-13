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
    header: str          # e.g. "x-api-key" or "Authorization"
    scheme: str | None   # e.g. "Bearer" or None

    def render(self, key: str) -> str:
        return f"{self.scheme} {key}" if self.scheme else key

    def extract(self, header_value: str) -> str:
        """Pull the bare credential out of an incoming header value."""
        if self.scheme and header_value.lower().startswith(self.scheme.lower() + " "):
            return header_value[len(self.scheme) + 1:].strip()
        return header_value.strip()


def parse_auth_style(style: str) -> AuthStyle:
    """'header:x-api-key' → (x-api-key, None); 'header:Authorization:Bearer' → (Authorization, Bearer)."""
    parts = style.split(":")
    if len(parts) < 2 or parts[0] != "header":
        raise ValueError(f"Unsupported auth_style: {style}")
    return AuthStyle(header=parts[1], scheme=parts[2] if len(parts) > 2 else None)
