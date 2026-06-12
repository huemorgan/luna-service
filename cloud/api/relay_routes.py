"""Composio webhook relay — public ingress + admin visibility (plan 015)."""

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import desc, select

from cloud.auth.deps import require_admin
from cloud.db.models import Agent, ComposioAccountLink, RelayDelivery
from cloud.db.session import get_session as get_db_session
from cloud.relay import standard_webhooks as sw
from cloud.relay.capture import extract_event_account, upsert_links

log = logging.getLogger(__name__)

router = APIRouter(tags=["relay"])

MAX_BODY_BYTES = 200 * 1024


def _composio_secret() -> str:
    return os.environ.get("CLOUD_COMPOSIO_WEBHOOK_SECRET", "")


# ── Public ingress ───────────────────────────────────────────────────────────

@router.post("/api/webhooks/composio", status_code=status.HTTP_202_ACCEPTED)
async def composio_ingress(request: Request):
    secret = _composio_secret()
    if not secret:
        log.warning("relay.webhook_rejected reason=no_secret_configured")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Webhook ingress not configured")

    raw_body = await request.body()
    if len(raw_body) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Body too large")

    webhook_id = request.headers.get("webhook-id", "")
    timestamp = request.headers.get("webhook-timestamp", "")
    signature = request.headers.get("webhook-signature", "")
    try:
        sw.verify(
            secret=secret,
            webhook_id=webhook_id,
            timestamp=timestamp,
            raw_body=raw_body,
            signature_header=signature,
        )
    except sw.WebhookAuthError as exc:
        log.warning("relay.webhook_rejected reason=%s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Signature verification failed")

    try:
        payload = json.loads(raw_body)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body is not JSON")

    connected_account = extract_event_account(payload)

    async with get_db_session() as db:
        existing = (await db.execute(
            select(RelayDelivery).where(RelayDelivery.webhook_id == webhook_id)
        )).scalar_one_or_none()
        if existing:
            return {"status": "duplicate", "delivery_id": str(existing.id)}

        agent_id = None
        if connected_account:
            link = (await db.execute(
                select(ComposioAccountLink).where(
                    ComposioAccountLink.connected_account_id == connected_account
                )
            )).scalar_one_or_none()
            agent_id = link.agent_id if link else None

        delivery = RelayDelivery(
            webhook_id=webhook_id,
            connected_account_id=connected_account,
            agent_id=agent_id,
            status="pending" if agent_id else "unroutable",
            body=raw_body.decode("utf-8", errors="replace"),
        )
        db.add(delivery)
        await db.commit()
        await db.refresh(delivery)

    if not agent_id:
        log.warning(
            "relay.unroutable webhook_id=%s connected_account=%s",
            webhook_id, connected_account,
        )
    return {"status": delivery.status, "delivery_id": str(delivery.id)}


# ── Admin: deliveries + links ────────────────────────────────────────────────

@router.get("/api/admin/relay/deliveries")
async def list_deliveries(limit: int = 100, admin=Depends(require_admin)):
    async with get_db_session() as db:
        rows = (await db.execute(
            select(RelayDelivery, Agent.slug)
            .outerjoin(Agent, Agent.id == RelayDelivery.agent_id)
            .order_by(desc(RelayDelivery.created_at))
            .limit(min(limit, 500))
        )).all()
        return [
            {
                "id": str(d.id),
                "webhook_id": d.webhook_id,
                "connected_account_id": d.connected_account_id,
                "agent_slug": slug,
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


@router.get("/api/admin/relay/links")
async def list_links(admin=Depends(require_admin)):
    async with get_db_session() as db:
        rows = (await db.execute(
            select(ComposioAccountLink, Agent.slug)
            .outerjoin(Agent, Agent.id == ComposioAccountLink.agent_id)
            .order_by(desc(ComposioAccountLink.created_at))
        )).all()
        return [
            {
                "connected_account_id": l.connected_account_id,
                "agent_id": str(l.agent_id),
                "agent_slug": slug,
                "app_name": l.app_name,
                "source": l.source,
                "created_at": l.created_at.isoformat() if l.created_at else None,
                "last_seen_at": l.last_seen_at.isoformat() if l.last_seen_at else None,
            }
            for l, slug in rows
        ]


class LinkBody(BaseModel):
    connected_account_id: str
    agent_slug: str
    app_name: str | None = None


@router.post("/api/admin/relay/links", status_code=status.HTTP_201_CREATED)
async def create_link(body: LinkBody, admin=Depends(require_admin)):
    if not body.connected_account_id.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "connected_account_id required")
    async with get_db_session() as db:
        agent = (await db.execute(
            select(Agent).where(Agent.slug == body.agent_slug)
        )).scalar_one_or_none()
        if not agent:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        await upsert_links(
            db, agent.id,
            [(body.connected_account_id.strip(), body.app_name)],
            source="admin",
        )
        await db.commit()
    return {"ok": True}


@router.delete("/api/admin/relay/links/{connected_account_id}")
async def delete_link(connected_account_id: str, admin=Depends(require_admin)):
    async with get_db_session() as db:
        link = (await db.execute(
            select(ComposioAccountLink).where(
                ComposioAccountLink.connected_account_id == connected_account_id
            )
        )).scalar_one_or_none()
        if not link:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
        await db.delete(link)
        await db.commit()
    return {"ok": True}
