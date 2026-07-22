"""Plan 052 §4 — tenant ElevenLabs keys pushed to the WhatsApp gateway.

The gateway synthesizes voice notes itself, so the tenant's elevenlabs key
(gateway_keys, agent scope first) must reach the wa account: on agent
connect, and when an admin adds an agent-scoped elevenlabs key.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

import cloud.whatsapp.provision as prov
from cloud import config
from cloud.db.models import Agent, GatewayKey, GatewayService
from cloud.gateway.crypto import encrypt_key
from cloud.gateway.registry import default_names
from cloud.gateway.tokens import issue_token

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    s = config.get_settings()
    monkeypatch.setattr(s, "whatsapp_gateway_url", "https://wa.example.com", raising=False)
    monkeypatch.setattr(s, "whatsapp_gateway_admin_key", "test-key", raising=False)
    monkeypatch.setattr(s, "base_url", "https://luna.test", raising=False)


def _gw_response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = "gw"
    return resp


async def _eleven_service(db):
    db.add(GatewayService(
        slug="elevenlabs", display_name="ElevenLabs", upstream_url="https://api.elevenlabs.io",
        auth_style="header:xi-api-key", **default_names("elevenlabs"),
    ))
    await db.commit()


async def _eleven_key(db, scope, value, priority=1):
    db.add(GatewayKey(service_slug="elevenlabs", scope=scope, priority=priority,
                      api_key_enc=encrypt_key(value), label="", is_active=True))
    await db.commit()


async def _mark_whatsapp_installed(db, agent):
    row = (await db.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()
    row.config_overrides = {**(row.config_overrides or {}), "installed_plugins": ["plugin-whatsapp"]}
    await db.commit()


# ── connect pushes the effective key ─────────────────────────────────────────

async def test_connect_pushes_agent_scoped_key(anon_client, db_session, sample_agent):
    await _eleven_service(db_session)
    await _eleven_key(db_session, f"agent:{sample_agent.id}", "tenant-11labs-key")
    tok = await issue_token(db_session, sample_agent.id)

    gw = AsyncMock(side_effect=[
        _gw_response(201, {"account_id": sample_agent.slug, "status": "linking"}),
        _gw_response(200, {"ok": True}),
    ])
    with patch.object(prov, "_gateway", gw):
        res = await anon_client.post("/api/agent/whatsapp/connect",
                                     headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200
    assert res.json()["voice_key_pushed"] is True
    method, path, payload = gw.call_args_list[1][0]
    assert (method, path) == ("PATCH", f"/accounts/{sample_agent.slug}")
    assert payload == {"eleven_key": "tenant-11labs-key"}


async def test_connect_falls_back_to_global_key(anon_client, db_session, sample_agent):
    await _eleven_service(db_session)
    await _eleven_key(db_session, "global", "global-11labs-key")
    tok = await issue_token(db_session, sample_agent.id)

    gw = AsyncMock(side_effect=[_gw_response(201, {}), _gw_response(200, {})])
    with patch.object(prov, "_gateway", gw):
        res = await anon_client.post("/api/agent/whatsapp/connect",
                                     headers={"Authorization": f"Bearer {tok}"})
    assert res.json()["voice_key_pushed"] is True
    assert gw.call_args_list[1][0][2] == {"eleven_key": "global-11labs-key"}


async def test_connect_without_key_pushes_nothing(anon_client, db_session, sample_agent):
    tok = await issue_token(db_session, sample_agent.id)
    gw = AsyncMock(return_value=_gw_response(201, {}))
    with patch.object(prov, "_gateway", gw):
        res = await anon_client.post("/api/agent/whatsapp/connect",
                                     headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200
    assert res.json()["voice_key_pushed"] is False
    assert gw.call_count == 1  # only the account POST — no PATCH


async def test_connect_survives_push_failure(anon_client, db_session, sample_agent):
    await _eleven_service(db_session)
    await _eleven_key(db_session, "global", "k")
    tok = await issue_token(db_session, sample_agent.id)
    gw = AsyncMock(side_effect=[_gw_response(201, {}), RuntimeError("gateway down")])
    with patch.object(prov, "_gateway", gw):
        res = await anon_client.post("/api/agent/whatsapp/connect",
                                     headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200  # connect never fails over voice
    assert res.json()["voice_key_pushed"] is False


# ── admin add_key pushes for agent-scoped elevenlabs ─────────────────────────

async def _add_key(admin_client, scope, slug="elevenlabs", api_key="new-key"):
    return await admin_client.post(
        f"/api/admin/gateway/services/{slug}/keys",
        json={"scope": scope, "priority": 1, "api_key": api_key, "label": "t"},
    )


async def test_add_agent_key_pushes_to_wa_account(admin_client, db_session, sample_agent):
    await _eleven_service(db_session)
    await _mark_whatsapp_installed(db_session, sample_agent)

    gw = AsyncMock(return_value=_gw_response(200, {}))
    with patch.object(prov, "_gateway", gw):
        res = await _add_key(admin_client, f"agent:{sample_agent.id}", api_key="fresh-key")
    assert res.status_code == 201
    gw.assert_called_once()
    method, path, payload = gw.call_args[0]
    assert (method, path) == ("PATCH", f"/accounts/{sample_agent.slug}")
    assert payload == {"eleven_key": "fresh-key"}


async def test_add_agent_key_without_whatsapp_skips_push(admin_client, db_session, sample_agent):
    await _eleven_service(db_session)  # plugin-whatsapp NOT installed

    gw = AsyncMock(return_value=_gw_response(200, {}))
    with patch.object(prov, "_gateway", gw):
        res = await _add_key(admin_client, f"agent:{sample_agent.id}")
    assert res.status_code == 201
    gw.assert_not_called()


async def test_add_global_key_skips_push(admin_client, db_session, sample_agent):
    await _eleven_service(db_session)
    await _mark_whatsapp_installed(db_session, sample_agent)

    gw = AsyncMock(return_value=_gw_response(200, {}))
    with patch.object(prov, "_gateway", gw):
        res = await _add_key(admin_client, "global")
    assert res.status_code == 201
    gw.assert_not_called()
