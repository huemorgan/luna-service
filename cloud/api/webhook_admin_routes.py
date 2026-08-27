"""Admin monitoring + management for generic webhook endpoints (plan 076).

Read-only listing of every minted hook (never the secrets) plus queue-mode
delivery history, and enable/disable/delete controls. Follows the
relay_routes admin pattern: require_admin + plain dict responses.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import desc, select

from cloud.api.webhook_agent_routes import public_hook_url
from cloud.auth.deps import require_admin
from cloud.db.models import Agent, RelayDelivery, WebhookEndpoint
from cloud.db.session import get_session as get_db_session

log = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks-admin"])


def _endpoint_row(ep: WebhookEndpoint, agent_slug: str | None, agent_name: str | None) -> dict:
    return {
        "id": str(ep.id),
        "agent_slug": agent_slug,
        "agent_name": agent_name,
        "name": ep.name,
        "plugin": ep.plugin,
        "hook_slug": ep.hook_slug,
        "public_url": public_hook_url(agent_slug or "", ep.hook_slug),
        "target_path": ep.target_path,
        "mode": ep.mode,
        "enabled": ep.enabled,
        "created_at": ep.created_at.isoformat() if ep.created_at else None,
        "last_delivery_at": ep.last_delivery_at.isoformat() if ep.last_delivery_at else None,
        "delivery_count": ep.delivery_count,
        "last_status_code": ep.last_status_code,
    }


@router.get("/api/admin/webhooks/endpoints")
async def list_endpoints(agent_slug: str | None = None, admin=Depends(require_admin)):
    async with get_db_session() as db:
        stmt = (
            select(WebhookEndpoint, Agent.slug, Agent.name)
            .outerjoin(Agent, Agent.id == WebhookEndpoint.agent_id)
            .order_by(desc(WebhookEndpoint.created_at))
        )
        if agent_slug:
            stmt = stmt.where(Agent.slug == agent_slug)
        rows = (await db.execute(stmt)).all()
        return [_endpoint_row(ep, slug, name) for ep, slug, name in rows]


@router.get("/api/admin/webhooks/deliveries")
async def list_hook_deliveries(
    limit: int = 100, agent_slug: str | None = None, admin=Depends(require_admin)
):
    """Queue-mode deliveries for generic hooks only (webhook_id `hook_…`);
    composio trigger deliveries stay on /api/admin/relay/deliveries."""
    async with get_db_session() as db:
        stmt = (
            select(RelayDelivery, Agent.slug)
            .outerjoin(Agent, Agent.id == RelayDelivery.agent_id)
            .where(RelayDelivery.webhook_id.like("hook_%"))
            .order_by(desc(RelayDelivery.created_at))
            .limit(min(limit, 500))
        )
        if agent_slug:
            stmt = stmt.where(Agent.slug == agent_slug)
        rows = (await db.execute(stmt)).all()
        return [
            {
                "id": str(d.id),
                "webhook_id": d.webhook_id,
                "agent_slug": slug,
                "target_path": d.target_path,
                "status": d.status,
                "attempts": d.attempts,
                "last_status_code": d.last_status_code,
                "last_error": d.last_error,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
                "next_attempt_at": d.next_attempt_at.isoformat() if d.next_attempt_at else None,
            }
            for d, slug in rows
        ]


async def _get_endpoint(db, endpoint_id: str) -> WebhookEndpoint:
    try:
        eid = uuid.UUID(endpoint_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown endpoint")
    ep = (await db.execute(
        select(WebhookEndpoint).where(WebhookEndpoint.id == eid)
    )).scalar_one_or_none()
    if not ep:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown endpoint")
    return ep


@router.patch("/api/admin/webhooks/endpoints/{endpoint_id}")
async def update_endpoint(
    endpoint_id: str, payload: dict = Body(...), admin=Depends(require_admin)
):
    async with get_db_session() as db:
        ep = await _get_endpoint(db, endpoint_id)
        if "enabled" in payload:
            ep.enabled = bool(payload["enabled"])
        await db.commit()
        await db.refresh(ep)
        agent = (await db.execute(
            select(Agent).where(Agent.id == ep.agent_id)
        )).scalar_one_or_none()
        return _endpoint_row(ep, agent.slug if agent else None, agent.name if agent else None)


@router.delete("/api/admin/webhooks/endpoints/{endpoint_id}")
async def delete_endpoint(endpoint_id: str, admin=Depends(require_admin)):
    async with get_db_session() as db:
        ep = await _get_endpoint(db, endpoint_id)
        await db.delete(ep)
        await db.commit()
    return {"ok": True}
