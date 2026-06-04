"""Agent CRUD routes — list, create, start, stop, retry, destroy."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from cloud.auth.deps import require_active_account
from cloud.db.models import Account, Agent, User
from cloud.db.session import get_session as get_db_session

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])


class CreateAgentRequest(BaseModel):
    name: str = "My Luna"


def _agent_dict(a: Agent) -> dict:
    return {
        "id": str(a.id),
        "name": a.name,
        "status": a.status,
        "runtime_kind": a.runtime_kind,
        "internal_url": a.internal_url,
        "error_message": a.error_message,
        "error_at": a.error_at.isoformat() if a.error_at else None,
        "created_at": a.created_at.isoformat(),
        "last_active_at": a.last_active_at.isoformat() if a.last_active_at else None,
    }


@router.get("")
async def list_agents(auth: tuple[User, Account] = Depends(require_active_account)):
    _, account = auth
    async with get_db_session() as db:
        agents = (await db.execute(
            select(Agent).where(Agent.account_id == account.id).order_by(Agent.created_at)
        )).scalars().all()

    return [_agent_dict(a) for a in agents]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: CreateAgentRequest,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    user, account = auth

    async with get_db_session() as db:
        agent = Agent(
            account_id=account.id,
            creator_id=user.id,
            name=body.name.strip() or "My Luna",
            status="provisioning",
        )
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
        agent_id = str(agent.id)
        result = _agent_dict(agent)

    from cloud.provisioning.workflow import provision_luna_for_account
    asyncio.create_task(provision_luna_for_account(str(account.id), agent_id=agent_id))

    return result


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()

    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return _agent_dict(agent)


@router.post("/{agent_id}/start")
async def start_agent(
    agent_id: str,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        if agent.status == "running":
            return _agent_dict(agent)
        if not agent.runtime_ref:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Agent has no runtime to start")

        from cloud.provisioning.workflow import _get_runtime
        from cloud.runtime.base import RuntimeHandle
        runtime = _get_runtime()
        handle = RuntimeHandle(agent.runtime_kind or "fly-machine", agent.runtime_ref, agent.internal_url or "")
        try:
            await runtime.start(handle) if hasattr(runtime, 'start') else None
            agent.status = "running"
            agent.error_message = None
        except Exception as e:
            agent.status = "error"
            agent.error_message = str(e)
            agent.error_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(agent)
        return _agent_dict(agent)


@router.post("/{agent_id}/stop")
async def stop_agent(
    agent_id: str,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        if agent.status == "stopped":
            return _agent_dict(agent)
        if not agent.runtime_ref:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Agent has no runtime to stop")

        from cloud.provisioning.workflow import _get_runtime
        from cloud.runtime.base import RuntimeHandle
        runtime = _get_runtime()
        handle = RuntimeHandle(agent.runtime_kind or "fly-machine", agent.runtime_ref, agent.internal_url or "")
        try:
            await runtime.stop(handle)
            agent.status = "stopped"
        except Exception as e:
            agent.status = "error"
            agent.error_message = str(e)
            agent.error_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(agent)
        return _agent_dict(agent)


@router.post("/{agent_id}/retry")
async def retry_agent(
    agent_id: str,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

        agent.status = "provisioning"
        agent.error_message = None
        agent.error_at = None
        await db.commit()
        await db.refresh(agent)
        result = _agent_dict(agent)

    from cloud.provisioning.workflow import provision_luna_for_account
    asyncio.create_task(provision_luna_for_account(str(account.id), agent_id=agent_id))
    return result


@router.delete("/{agent_id}")
async def destroy_agent(
    agent_id: str,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                Agent.account_id == account.id,
            )
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

        if agent.runtime_ref:
            from cloud.provisioning.workflow import _get_runtime
            from cloud.runtime.base import RuntimeHandle
            runtime = _get_runtime()
            handle = RuntimeHandle(agent.runtime_kind or "fly-machine", agent.runtime_ref, agent.internal_url or "")
            try:
                await runtime.destroy(handle)
            except Exception as e:
                log.warning("Failed to destroy runtime for agent %s: %s", agent_id, e)

        await db.delete(agent)
        await db.commit()

    return {"ok": True}
