"""Plan 026 — plugin↔service membership.

The single source of truth for "which plugins does this agent effectively run"
and "which gateway services do those plugins bind to". Consumed by membership-
driven provisioning (`provision_env.build_gateway_env`) and the agent-facing
discovery endpoint (`gateway_agent_routes`).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.db.models import PluginCatalogEntry


def _norm(name: str) -> str:
    return name.strip().lower()


def effective_plugin_names(
    image_config: dict | None, agent_overrides: dict | None,
) -> set[str]:
    """Plugins an agent effectively runs.

    = the baked set (``image_config["plugin_set"]`` — the *default* list) ∪ the
    opt-in plugins the agent installed (``config_overrides["installed_plugins"]``,
    tracked by the install hook). Names are normalised (lowercase).
    """
    names: set[str] = set()
    for entry in (image_config or {}).get("plugin_set") or []:
        if isinstance(entry, dict) and entry.get("name"):
            names.add(_norm(str(entry["name"])))
        elif isinstance(entry, str):
            names.add(_norm(entry))
    for name in (agent_overrides or {}).get("installed_plugins") or []:
        if isinstance(name, str) and name:
            names.add(_norm(name))
    return names


async def bindings_for_plugins(
    db: AsyncSession, plugin_names: set[str],
) -> list[PluginCatalogEntry]:
    """Enabled catalog rows for the given plugin names that actually bind a service."""
    if not plugin_names:
        return []
    rows = (await db.execute(
        select(PluginCatalogEntry).where(
            PluginCatalogEntry.enabled.is_(True),
            PluginCatalogEntry.service_slug.isnot(None),
        )
    )).scalars().all()
    return [r for r in rows if _norm(r.plugin_name) in plugin_names]
