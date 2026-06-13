"""Plan 016 — per-service config resolver tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cloud.db.models import GatewayService
from cloud.gateway.crypto import encrypt_key
from cloud.gateway.provision_env import build_gateway_env
from cloud.gateway.registry import seed_services
from cloud.provisioning.services_config import (
    hosted_composio_key_provisioned,
    resolve_composio_accounts_mode,
)


async def _enable_composio(db):
    svc = (await db.execute(
        select(GatewayService).where(GatewayService.slug == "composio")
    )).scalar_one()
    svc.enabled = True
    svc.provision_by_default = True
    await db.flush()


# ── Resolver unit tests (pure, sync) ─────────────────────────────────────────


def test_resolver_builtin_default_with_hosted_key():
    assert resolve_composio_accounts_mode(None, None, hosted_key_provisioned=True) == "both"


def test_resolver_builtin_default_without_hosted_key():
    assert resolve_composio_accounts_mode(None, None, hosted_key_provisioned=False) == "user"


def test_resolver_image_default_overrides_builtin():
    image_cfg = {"services": {"composio": {"accounts_mode": "hosted"}}}
    assert resolve_composio_accounts_mode(image_cfg, None, hosted_key_provisioned=False) == "hosted"


def test_resolver_agent_override_wins():
    image_cfg = {"services": {"composio": {"accounts_mode": "hosted"}}}
    agent_ov = {"services": {"composio": {"accounts_mode": "user"}}}
    assert resolve_composio_accounts_mode(image_cfg, agent_ov, hosted_key_provisioned=True) == "user"


def test_resolver_invalid_value_falls_through():
    image_cfg = {"services": {"composio": {"accounts_mode": "nonsense"}}}
    agent_ov = {"services": {"composio": {"accounts_mode": "garbage"}}}
    # Both bogus → fall through to the builtin.
    assert resolve_composio_accounts_mode(image_cfg, agent_ov, hosted_key_provisioned=True) == "both"


def test_resolver_missing_nested_keys_are_safe():
    # Various malformed shapes shouldn't crash, just be ignored.
    bad_shapes = [
        {},
        {"services": None},
        {"services": "not-a-dict"},
        {"services": {"composio": None}},
        {"services": {"composio": "string"}},
        {"services": {"other": {"accounts_mode": "hosted"}}},
    ]
    for shape in bad_shapes:
        assert resolve_composio_accounts_mode(shape, None, hosted_key_provisioned=True) == "both"
        assert resolve_composio_accounts_mode(None, shape, hosted_key_provisioned=False) == "user"


def test_resolver_agent_invalid_falls_through_to_image():
    """Agent has bogus value → use image default, not the builtin."""
    image_cfg = {"services": {"composio": {"accounts_mode": "hosted"}}}
    agent_ov = {"services": {"composio": {"accounts_mode": "nonsense"}}}
    assert resolve_composio_accounts_mode(image_cfg, agent_ov, hosted_key_provisioned=True) == "hosted"


# ── hosted_composio_key_provisioned (async, hits DB) ─────────────────────────

pytestmark_async = pytest.mark.asyncio


@pytest.mark.asyncio
async def test_hosted_key_false_when_no_service_row(db_session):
    assert await hosted_composio_key_provisioned(db_session) is False


@pytest.mark.asyncio
async def test_hosted_key_false_when_disabled(db_session):
    await seed_services(db_session)
    await db_session.commit()
    # Composio is seeded with enabled=False — even with a key it should report False.
    assert await hosted_composio_key_provisioned(db_session) is False


@pytest.mark.asyncio
async def test_hosted_key_false_when_no_keys(db_session):
    await seed_services(db_session)
    await _enable_composio(db_session)
    await db_session.commit()
    assert await hosted_composio_key_provisioned(db_session) is False


@pytest.mark.asyncio
async def test_hosted_key_true_when_active_key_in_pool(db_session):
    from cloud.db.models import GatewayKey

    await seed_services(db_session)
    await _enable_composio(db_session)
    db_session.add(GatewayKey(
        service_slug="composio",
        scope="global",
        priority=1,
        api_key_enc=encrypt_key("composio-real"),
        label="prod",
        is_active=True,
    ))
    await db_session.commit()
    assert await hosted_composio_key_provisioned(db_session) is True


# ── build_gateway_env wiring ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_gateway_env_default_when_unspecified(db_session, sample_agent):
    await seed_services(db_session)
    await db_session.commit()
    env = await build_gateway_env(db_session, sample_agent.id)
    # Composio not provisioned in seeds → fallback is "user".
    assert env["LUNA_CONNECTORS_ACCOUNTS_MODE"] == "user"


@pytest.mark.asyncio
async def test_build_gateway_env_image_default(db_session, sample_agent):
    await seed_services(db_session)
    await db_session.commit()
    env = await build_gateway_env(
        db_session, sample_agent.id,
        image_config={"services": {"composio": {"accounts_mode": "hosted"}}},
    )
    assert env["LUNA_CONNECTORS_ACCOUNTS_MODE"] == "hosted"


@pytest.mark.asyncio
async def test_build_gateway_env_agent_override(db_session, sample_agent):
    await seed_services(db_session)
    await db_session.commit()
    env = await build_gateway_env(
        db_session, sample_agent.id,
        image_config={"services": {"composio": {"accounts_mode": "hosted"}}},
        agent_overrides={"services": {"composio": {"accounts_mode": "user"}}},
    )
    assert env["LUNA_CONNECTORS_ACCOUNTS_MODE"] == "user"
