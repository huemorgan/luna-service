"""Registry-driven env injection for tenant machines.

Replaces the hardcoded real-key loop in provisioning: machines get proxy
base URLs + one lsv1- tenant token, never a real provider key.
"""

from __future__ import annotations

import logging
import os
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.config import get_settings
from cloud.db.models import GatewayService
from cloud.gateway.tokens import issue_token

log = logging.getLogger(__name__)

HOST_NAME = "Luna Cloud"

# Services Luna can't route through the proxy yet (no base-url support on the
# Luna side until 007.001 lands). The real key keeps being injected for these.
LEGACY_REAL_KEY_VARS = ("LUNA_TAVILY_API_KEY",)


async def build_gateway_env(db: AsyncSession, agent_id: uuid.UUID) -> dict[str, str]:
    """Env vars for a tenant machine: proxy URLs + tenant token + branding."""
    settings = get_settings()
    base = settings.base_url.rstrip("/")

    token = await issue_token(db, agent_id)

    services = (await db.execute(
        select(GatewayService).where(
            GatewayService.enabled.is_(True),
            GatewayService.provision_by_default.is_(True),
        )
    )).scalars().all()

    env: dict[str, str] = {"LUNA_HOST_NAME": HOST_NAME}
    for svc in services:
        env[svc.luna_env_base_url_var] = f"{base}/proxy/{svc.slug}"
        env[svc.luna_env_key_var] = token
        # Also emit the SDK-standard vars (ANTHROPIC_BASE_URL, OPENAI_API_KEY,
        # …). Luna's pydantic-ai chat path builds default SDK clients, which
        # read these directly — without them chat bypasses the gateway and
        # sends the lsv1 token straight to the provider (401).
        for luna_var in (svc.luna_env_base_url_var, svc.luna_env_key_var):
            if luna_var.startswith("LUNA_"):
                env[luna_var.removeprefix("LUNA_")] = env[luna_var]

    # Legacy exception — documented in plan 013 / tests 07.
    for var in LEGACY_REAL_KEY_VARS:
        val = os.environ.get(var, "")
        if val:
            env[var] = val

    log.info(
        "gateway env for agent %s: %s (+ %d legacy vars)",
        agent_id,
        [s.slug for s in services],
        sum(1 for v in LEGACY_REAL_KEY_VARS if os.environ.get(v)),
    )
    return env
