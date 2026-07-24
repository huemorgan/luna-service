"""060/fix3 — token rotation ordering.

Production showed "Invalid tenant token" 401 storms whenever an agent was
recreated or an admin rotated a token: the live token was revoked BEFORE the
new one reached the machine. These tests pin the fixed ordering:

- `_provision_core` mints with revoke_existing=False, revokes the old token
  only after the runtime reports success, and drops the undelivered new token
  (keeping the old one) when provisioning fails.
- the admin token route keeps existing tokens valid by default.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

from cloud.gateway.tokens import issue_token, verify_token

pytestmark = pytest.mark.asyncio


# ── Admin route: default no longer revokes the live token ────────────────────

async def test_issue_agent_token_route_keeps_live_token(admin_client, db_session, sample_agent):
    old = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    resp = await admin_client.post(f"/api/admin/gateway/agents/{sample_agent.id}/token")
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"].startswith("lsv1-")
    assert "remain valid" in body["note"]

    # the machine's live token still works — no 401 storm
    assert await verify_token(db_session, old) == sample_agent.id
    assert await verify_token(db_session, body["token"]) == sample_agent.id


async def test_issue_agent_token_route_explicit_revoke(admin_client, db_session, sample_agent):
    old = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    resp = await admin_client.post(
        f"/api/admin/gateway/agents/{sample_agent.id}/token?revoke_existing=true"
    )
    assert resp.status_code == 200
    assert await verify_token(db_session, old) is None
    assert await verify_token(db_session, resp.json()["token"]) == sample_agent.id


# ── _provision_core ordering ──────────────────────────────────────────────────

class _FakeTenantDb:
    role = "role_x"
    password = "pw"  # noqa: S105 — test fixture
    db_name = "tenant_x"


class _FakeHandle:
    runtime_kind = "fly-machine"
    runtime_ref = "machine-xyz"
    internal_url = "https://luna-agents.fly.dev"
    extra: dict = {}


def _workflow_patches(factory, *, provision_ok: bool):
    """Patch every workflow collaborator so `_provision_core` runs against the
    test DB with a stubbed runtime."""
    import cloud.provisioning.workflow as wf

    @asynccontextmanager
    async def _sess():
        async with factory() as s:
            yield s

    async def _fake_provision_db(admin_url, slug):
        return _FakeTenantDb()

    class _FakeRuntime:
        async def provision(self, spec):
            if not provision_ok:
                raise RuntimeError("boom: machine failed to boot")
            # the machine received spec.llm_keys (incl. the new token) — ok
            return _FakeHandle()

    async def _fake_catalog(db):
        return []

    async def _fake_defaults(db):
        return {}

    return (
        patch.object(wf, "get_db_session", _sess),
        patch.object(wf, "provision_tenant_database", _fake_provision_db),
        patch.object(wf, "_get_runtime", lambda: _FakeRuntime()),
        patch.object(wf, "system_catalog", _fake_catalog),
        patch.object(wf, "resolved_default_config", _fake_defaults),
        patch.object(
            wf, "resolve_default_heads",
            lambda *a, **k: {"primary": "anthropic:x", "fast": "anthropic:y"},
        ),
    )


async def _run_provision_core(db_engine, account, agent, *, provision_ok: bool):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import cloud.provisioning.workflow as wf

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    patches = _workflow_patches(factory, provision_ok=provision_ok)
    ctx = [p.__enter__() for p in patches]
    try:
        return await wf._provision_core(
            account, agent, image_tag="registry/img:1", image_version="1",
            image_config={},
        )
    finally:
        for p in patches:
            p.__exit__(None, None, None)
        del ctx


async def test_recreate_revokes_old_token_only_after_success(
    db_engine, db_session, account, sample_agent
):
    old = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    await _run_provision_core(db_engine, account, sample_agent, provision_ok=True)

    tokens = []
    from sqlalchemy import select

    from cloud.db.models import GatewayTenantToken
    rows = (await db_session.execute(
        select(GatewayTenantToken).where(GatewayTenantToken.agent_id == sample_agent.id)
    )).scalars().all()
    tokens = [(r.token_hash, r.revoked_at) for r in rows]
    # two tokens exist: the old one (revoked post-success) + the live new one
    assert len(tokens) == 2
    assert await verify_token(db_session, old) is None
    assert sum(1 for _, revoked in tokens if revoked is None) == 1


async def test_failed_recreate_keeps_old_token_valid(
    db_engine, db_session, account, sample_agent
):
    old = await issue_token(db_session, sample_agent.id)
    await db_session.commit()

    with pytest.raises(RuntimeError, match="boom"):
        await _run_provision_core(db_engine, account, sample_agent, provision_ok=False)

    # the running old machine keeps its valid token; the undelivered new token
    # is revoked, not left dangling
    assert await verify_token(db_session, old) == sample_agent.id
    from sqlalchemy import select

    from cloud.db.models import GatewayTenantToken
    rows = (await db_session.execute(
        select(GatewayTenantToken).where(GatewayTenantToken.agent_id == sample_agent.id)
    )).scalars().all()
    assert sum(1 for r in rows if r.revoked_at is None) == 1  # only `old`
