"""Plan 042 — stable per-agent LUNA_JWT_SECRET.

Without it, Luna persists a random JWT secret in the machine's ephemeral HOME
and every Fly restart invalidates all outstanding tokens (the recurring wiki
pane 401). The control plane derives a stable secret per agent and injects it
at provision time; the 029 env backfill rolls it out to existing machines.
"""

from __future__ import annotations

import uuid

import pytest

from cloud.runtime.base import AgentSpec
from cloud.runtime.proxy_secret import derive_jwt_secret, derive_proxy_secret
from cloud.tests.test_fly_volumes import FakeFly, _runtime


def _spec(**kw) -> AgentSpec:
    return AgentSpec(
        account_slug="acct",
        agent_slug="acct-my-luna",
        db_schema="",
        db_url="postgresql+asyncpg://u:p@h/db",
        vault_key="ab" * 32,
        trusted_proxy_secret="secret",
        **kw,
    )


def test_jwt_secret_deterministic_and_distinct():
    root = "root-secret"
    a = str(uuid.uuid4())
    b = str(uuid.uuid4())
    assert derive_jwt_secret(root, a) == derive_jwt_secret(root, a)
    assert derive_jwt_secret(root, a) != derive_jwt_secret(root, b)
    assert derive_jwt_secret("other", a) != derive_jwt_secret(root, a)
    # hex, 64 chars (sha256)
    assert len(derive_jwt_secret(root, a)) == 64
    int(derive_jwt_secret(root, a), 16)


def test_jwt_secret_differs_from_proxy_secret():
    # Same root + agent must never yield the same value for both purposes:
    # the proxy secret travels in request headers, the JWT secret signs tokens.
    root = "root-secret"
    agent = str(uuid.uuid4())
    assert derive_jwt_secret(root, agent) != derive_proxy_secret(root, agent)


@pytest.mark.asyncio
async def test_fly_provision_injects_jwt_secret():
    fake = FakeFly()
    rt = _runtime(fake)

    await rt.provision(_spec(jwt_secret="stable-jwt"))

    post_machine = next(c for c in fake.calls if c[0] == "POST" and c[1] == "/machines")
    env = post_machine[2]["config"]["env"]
    assert env["LUNA_JWT_SECRET"] == "stable-jwt"


@pytest.mark.asyncio
async def test_fly_provision_omits_jwt_secret_when_unset():
    # Pre-042 specs (jwt_secret="") must not inject an empty secret — Luna
    # would sign tokens with "" instead of self-managing.
    fake = FakeFly()
    rt = _runtime(fake)

    await rt.provision(_spec())

    post_machine = next(c for c in fake.calls if c[0] == "POST" and c[1] == "/machines")
    assert "LUNA_JWT_SECRET" not in post_machine[2]["config"]["env"]
