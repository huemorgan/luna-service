"""039/007 — Stripe webhook ingress.

Auth here is the Stripe signature over the RAW body — this router is
mounted WITHOUT the same-origin dependency and must never grow cookie or
session dependencies. The route does no financial work: it verifies,
dedupes, and enqueues a durable job (intake_event); handlers on the 001
worker retrieve canonical objects and grant.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request, status

from cloud.billing.stripe_webhooks import intake_event
from cloud.billing.stripe_gateway import verify_webhook_signature
from cloud.config import get_settings
from cloud.db.session import get_session as get_db_session

log = logging.getLogger("billing.stripe")

router = APIRouter(prefix="/api/webhooks", tags=["stripe-webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request):
    s = get_settings()
    if not s.stripe_webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Stripe webhooks are not configured")
    body = await request.body()
    if not verify_webhook_signature(
        body, request.headers.get("stripe-signature"), s.stripe_webhook_secret
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature")
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid payload")
    if not isinstance(event, dict) or not event.get("id"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid payload")
    if bool(event.get("livemode")) != s.stripe_livemode:
        # A live event on a test deploy (or vice versa) is a config fault —
        # reject loudly so Stripe retries against the fixed deployment.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "livemode mismatch")
    async with get_db_session() as db:
        fresh = await intake_event(db, event)
        await db.commit()
    return {"received": True, "duplicate": not fresh}
