"""Plan 078 — zombie scheduled work (7a) + feedback ticket idempotency (7b).

Evidence: gateway_auth "Invalid tenant token" 3-hourly grids 08-31→09-04 from
deleted/re-provisioned machines; 08-31 five-ticket feedback cancel cascade.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from cloud.billing import hosting
from cloud.billing.models import BillingJob
from cloud.db.models import GatewayTenantToken
from cloud.gateway.tokens import issue_token
from cloud.scheduler_svc import provision, sweep

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ── 7a: teardown revokes tokens + disconnects scheduler ─────────────────────

async def test_teardown_revokes_tokens_and_disconnects_scheduler(
    db_session, account, sample_agent, monkeypatch,
):
    class FakeRuntime:
        async def destroy(self, handle):
            pass

    monkeypatch.setattr("cloud.provisioning.workflow._get_runtime", FakeRuntime)
    disconnected = []

    async def fake_disconnect(agent):
        disconnected.append(agent.slug)
        return {"deleted": True, "status_code": 204}

    monkeypatch.setattr(provision, "disconnect_agent", fake_disconnect)

    await issue_token(db_session, sample_agent.id)
    sample_agent.deleted_at = NOW
    job = BillingJob(job_type=hosting.TEARDOWN_JOB,
                     payload={"agent_id": str(sample_agent.id)})
    db_session.add(job)
    await db_session.flush()

    result = await hosting._handle_agent_teardown(db_session, job)
    assert result == {"torn_down": str(sample_agent.id)}
    assert disconnected == [sample_agent.slug]

    live = (await db_session.execute(
        select(GatewayTenantToken).where(
            GatewayTenantToken.agent_id == sample_agent.id,
            GatewayTenantToken.revoked_at.is_(None),
        )
    )).scalars().all()
    assert live == []


async def test_teardown_survives_scheduler_disconnect_failure(
    db_session, account, sample_agent, monkeypatch,
):
    class FakeRuntime:
        async def destroy(self, handle):
            pass

    monkeypatch.setattr("cloud.provisioning.workflow._get_runtime", FakeRuntime)

    async def broken_disconnect(agent):
        raise RuntimeError("scheduler service not configured")

    monkeypatch.setattr(provision, "disconnect_agent", broken_disconnect)
    sample_agent.deleted_at = NOW
    job = BillingJob(job_type=hosting.TEARDOWN_JOB,
                     payload={"agent_id": str(sample_agent.id)})
    db_session.add(job)
    await db_session.flush()
    result = await hosting._handle_agent_teardown(db_session, job)
    assert result == {"torn_down": str(sample_agent.id)}


# ── 7a: fire relay refuses tombstoned agents ────────────────────────────────

async def test_fire_relay_404_for_tombstoned_agent(anon_client, db_session, sample_agent):
    sample_agent.deleted_at = NOW
    db_session.add(sample_agent)
    await db_session.commit()
    res = await anon_client.post(
        f"/api/webhooks/scheduler/{sample_agent.slug}/fire", content=b"{}"
    )
    assert res.status_code == 404


# ── 7a: orphaned-account sweep ──────────────────────────────────────────────

async def test_sweep_deletes_accounts_with_no_live_agent(
    db_session, sample_agent, monkeypatch,
):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _test_session():
        yield db_session

    monkeypatch.setattr(sweep, "get_db_session", _test_session)
    monkeypatch.setattr(
        provision, "service_config", lambda: ("http://sched.test", "k")
    )
    stats = MagicMock(status_code=200)
    stats.json.return_value = {"accounts": [
        {"account_id": sample_agent.slug},
        {"account_id": "deleted-agent-slug"},
    ]}
    delete_resp = MagicMock(status_code=204)
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=stats)
    client.delete = AsyncMock(return_value=delete_resp)

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)

    result = await sweep.sweep_once()
    assert result == {"accounts": 2, "orphaned": 1, "deleted": 1}
    args, _ = client.delete.call_args
    assert args[0] == "http://sched.test/accounts/deleted-agent-slug"


async def test_sweep_skips_when_unconfigured(monkeypatch):
    monkeypatch.setattr(provision, "service_config", lambda: ("", ""))
    assert await sweep.sweep_once() == {"skipped": "unconfigured"}


# ── 7b: ticket idempotency on client_ref ────────────────────────────────────

async def _token(db_session, agent):
    tok = await issue_token(db_session, agent.id)
    await db_session.commit()
    return tok


def _ticket_payload(**over):
    base = {
        "origin": "agent",
        "category": "bug",
        "severity": "normal",
        "title": "The pane is blank",
        "body": "Repro: open the pane.",
        "client_ref": str(uuid.uuid4()),
    }
    base.update(over)
    return base


async def test_duplicate_client_ref_returns_existing_ticket(
    anon_client, db_session, sample_agent,
):
    tok = await _token(db_session, sample_agent)
    payload = _ticket_payload()
    first = await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok), json=payload
    )
    assert first.status_code == 201, first.text
    second = await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok), json=payload
    )
    assert second.status_code == 200, second.text
    dup = second.json()
    assert dup["duplicate"] is True
    assert dup["id"] == first.json()["id"]

    listing = (await anon_client.get(
        "/api/agent/feedback/tickets", headers=_auth(tok)
    )).json()
    assert len(listing["tickets"]) == 1


async def test_distinct_client_refs_create_distinct_tickets(
    anon_client, db_session, sample_agent,
):
    tok = await _token(db_session, sample_agent)
    r1 = await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok), json=_ticket_payload()
    )
    r2 = await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok),
        json=_ticket_payload(body="Different repro."),
    )
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]


async def test_missing_client_ref_still_creates(anon_client, db_session, sample_agent):
    tok = await _token(db_session, sample_agent)
    payload = _ticket_payload()
    payload.pop("client_ref")
    r1 = await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok), json=payload
    )
    r2 = await anon_client.post(
        "/api/agent/feedback/tickets", headers=_auth(tok), json=payload
    )
    # pre-0.7.0 clients keep today's behavior: every send is a new ticket
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]
