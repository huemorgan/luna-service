"""Agent routes — list and create (placeholder) agents."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from cloud.auth.deps import require_active_account
from cloud.db.models import Account, Agent, User
from cloud.db.session import get_session as get_db_session

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
async def list_agents(auth: tuple[User, Account] = Depends(require_active_account)):
    user, account = auth
    async with get_db_session() as db:
        agents = (await db.execute(
            select(Agent).where(Agent.account_id == account.id).order_by(Agent.created_at)
        )).scalars().all()

    return [
        {
            "id": str(a.id),
            "name": a.name,
            "status": a.status,
            "created_at": a.created_at.isoformat(),
            "last_active_at": a.last_active_at.isoformat() if a.last_active_at else None,
        }
        for a in agents
    ]


@router.post("", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def create_agent(auth: tuple[User, Account] = Depends(require_active_account)):
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        "Agent provisioning is not available yet — coming in phase 003.",
    )
