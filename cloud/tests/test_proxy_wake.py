"""Tests for the proxy auto-wake behavior."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestProxyAutoWake:
    """Test that the proxy auto-wakes stopped/crashed machines."""

    async def test_proxy_wakes_stopped_agent(self, admin_client: AsyncClient, sample_agent, db_session):
        """When agent status is 'stopped', proxy should try to wake it."""
        from cloud.db.models import Agent
        sample_agent.status = "stopped"
        await db_session.commit()

        mock_start = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.aiter_bytes = AsyncMock(return_value=AsyncMock())
        mock_response.aread = AsyncMock(return_value=b'{"ok": true}')
        mock_response.aclose = AsyncMock()

        with (
            patch("cloud.api.proxy._try_wake_agent", new_callable=AsyncMock, return_value=True),
            patch("cloud.api.proxy._proxy_request", new_callable=AsyncMock, return_value=MagicMock(status_code=200, body=b'ok')),
        ):
            from fastapi.responses import Response
            mock_resp = Response(content='{"ok":true}', status_code=200, media_type="application/json")
            with patch("cloud.api.proxy._proxy_request", new_callable=AsyncMock, return_value=mock_resp):
                resp = await admin_client.get(f"/a/{sample_agent.slug}/api/health")
                assert resp.status_code == 200

    async def test_proxy_returns_503_when_wake_fails(self, admin_client: AsyncClient, sample_agent, db_session):
        """When agent is stopped and wake fails, return 503."""
        sample_agent.status = "stopped"
        await db_session.commit()

        with patch("cloud.api.proxy._try_wake_agent", new_callable=AsyncMock, return_value=False):
            resp = await admin_client.get(f"/a/{sample_agent.slug}/api/health")
            assert resp.status_code == 503

    async def test_proxy_retries_after_connection_error(self, admin_client: AsyncClient, sample_agent):
        """When proxy gets a connection error, it should wake and retry."""
        import httpx
        from fastapi.responses import Response

        mock_resp = Response(content='{"ok":true}', status_code=200, media_type="application/json")
        call_count = 0

        async def mock_proxy(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("Connection refused")
            return mock_resp

        with (
            patch("cloud.api.proxy._proxy_request", side_effect=mock_proxy),
            patch("cloud.api.proxy._try_wake_agent", new_callable=AsyncMock, return_value=True),
        ):
            resp = await admin_client.get(f"/a/{sample_agent.slug}/api/health")
            assert resp.status_code == 200
            assert call_count == 2

    async def test_proxy_502_when_wake_and_retry_both_fail(self, admin_client: AsyncClient, sample_agent):
        """When proxy fails, wake succeeds, but retry also fails — return 502."""
        import httpx

        async def mock_proxy(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")

        with (
            patch("cloud.api.proxy._proxy_request", side_effect=mock_proxy),
            patch("cloud.api.proxy._try_wake_agent", new_callable=AsyncMock, return_value=True),
        ):
            resp = await admin_client.get(f"/a/{sample_agent.slug}/api/health")
            assert resp.status_code == 502

    async def test_proxy_no_runtime_ref_returns_503(self, admin_client: AsyncClient, sample_agent, db_session):
        """Agent with no runtime_ref should get 503."""
        sample_agent.runtime_ref = None
        await db_session.commit()

        resp = await admin_client.get(f"/a/{sample_agent.slug}/api/health")
        assert resp.status_code == 503

    async def test_proxy_updates_status_on_unreachable(self, admin_client: AsyncClient, sample_agent, db_session):
        """When machine is unreachable and can't be woken, DB status should update to 'error'."""
        import httpx
        from sqlalchemy import select
        from cloud.db.models import Agent

        async def mock_proxy(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")

        with (
            patch("cloud.api.proxy._proxy_request", side_effect=mock_proxy),
            patch("cloud.api.proxy._try_wake_agent", new_callable=AsyncMock, return_value=False),
        ):
            resp = await admin_client.get(f"/a/{sample_agent.slug}/api/health")
            assert resp.status_code == 502

        # Read from a fresh session to see the proxy's DB write
        from cloud.db.session import get_session as _get_session
        async with _get_session() as fresh_db:
            agent = (await fresh_db.execute(
                select(Agent).where(Agent.id == sample_agent.id)
            )).scalar_one()
            assert agent.status == "error"
            assert "unreachable" in (agent.error_message or "").lower()


class TestWakeLock:
    """Test that concurrent wake requests are serialized."""

    async def test_concurrent_wakes_only_start_once(self):
        """Multiple concurrent _try_wake_agent calls should only start the machine once."""
        from cloud.api.proxy import _try_wake_agent, _wake_locks
        from cloud.db.models import Agent

        start_count = 0

        async def mock_start(handle):
            nonlocal start_count
            start_count += 1
            await asyncio.sleep(0.1)

        agent = MagicMock(spec=Agent)
        agent.slug = "test-concurrent-wake"
        agent.runtime_ref = "machine-999"
        agent.runtime_kind = "fly-machine"
        agent.internal_url = "https://test.fly.dev"
        agent.id = "00000000-0000-0000-0000-000000000099"

        with (
            patch("os.environ.get", return_value="fake-token"),
            patch("cloud.runtime.fly_machines.FlyMachinesRuntime") as MockFly,
            patch("cloud.api.proxy.get_db_session") as mock_db,
        ):
            instance = MockFly.return_value
            instance.start = mock_start
            # Fail-fast existence check (plan 037): machine exists.
            instance.describe = AsyncMock(return_value={"id": "machine-999", "state": "stopped"})

            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_result = MagicMock()
            mock_result.scalar_one = MagicMock(return_value=agent)
            # 039/010: hosting_blocked resolves the effective billing mode —
            # no override row means the global mode (off) applies.
            mock_result.scalar_one_or_none = MagicMock(return_value=None)
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_db.return_value = mock_session

            # Clear any stale locks
            _wake_locks.pop("test-concurrent-wake", None)

            results = await asyncio.gather(
                _try_wake_agent(agent),
                _try_wake_agent(agent),
                _try_wake_agent(agent),
            )

            assert start_count == 1
            assert all(results)
