"""039/007 — Stripe webhook intake and durable handlers → grant issuance.

Intake (the route calls `intake_event`) dedupes into processed_webhooks and
enqueues a durable BillingJob in the same transaction — the event exists
iff its job does. Handlers run on the 001 worker and NEVER trust the event
payload: they retrieve the canonical object from Stripe, so out-of-order
delivery and replayed bodies are harmless. Everything is idempotent
end-to-end — grant lots dedupe on compound source keys
`stripe:{ref}:{product_key}:{paid|bonus|gift}:{lot_index}`, payments on
stripe_payments.payment_ref, and the subscription mirror is last-write
from canonical state.

`invoice.paid` alone is not proof of collected money: zero-value,
out-of-band, wrong-currency, or binding-mismatched invoices grant nothing.
"""

from __future__ import annotations

import calendar
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing import ledger, rating, stripe_clawback, worker
from cloud.billing.models import (
    BillingAccount,
    BillingJob,
    ProcessedWebhook,
    StripePayment,
    StripePriceBinding,
    StripeSubscription,
)
from cloud.billing.stripe_gateway import StripeGateway

log = logging.getLogger("billing.stripe")

# event type → durable job type. Unlisted events are acknowledged and dropped.
HANDLED_EVENTS = {
    "invoice.paid": "stripe.invoice_paid",
    "checkout.session.completed": "stripe.checkout_completed",
    "customer.subscription.created": "stripe.subscription_sync",
    "customer.subscription.updated": "stripe.subscription_sync",
    "customer.subscription.deleted": "stripe.subscription_sync",
    "charge.refunded": "stripe.charge_refunded",
    "charge.dispute.created": "stripe.dispute",
    "charge.dispute.closed": "stripe.dispute",
    "invoice.payment_failed": "stripe.invoice_failed",
}

# Tests replace this with a factory returning a MockTransport-backed gateway.
gateway_factory = StripeGateway.from_settings


class StripeConfigMissing(Exception):
    """Raised inside handlers when the gateway is unconfigured — the job
    retries with backoff and dead-letters visibly instead of vanishing."""


def _gateway() -> StripeGateway:
    gw = gateway_factory()
    if gw is None:
        raise StripeConfigMissing("Stripe is not configured")
    return gw


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ts(unix: int | None) -> datetime | None:
    return datetime.fromtimestamp(unix, tz=timezone.utc) if unix else None


def add_months_clamped(dt: datetime, months: int) -> datetime:
    """`dt` plus N calendar months, anchor day clamped to the target
    month's last day (Jan 31 + 1mo → Feb 28/29)."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=day)


# ── Intake (called by the webhook route, post-signature) ─────────────────────

async def intake_event(db: AsyncSession, event: dict) -> bool:
    """Record + enqueue one verified event. Returns False for duplicates.
    The ProcessedWebhook insert and the job share the caller's transaction."""
    event_id = event["id"]
    event_type = event.get("type", "")
    job_type = HANDLED_EVENTS.get(event_type)
    obj = (event.get("data") or {}).get("object") or {}
    existing = (
        await db.execute(
            select(ProcessedWebhook).where(
                ProcessedWebhook.provider == "stripe",
                ProcessedWebhook.event_id == event_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    db.add(ProcessedWebhook(
        provider="stripe",
        event_id=event_id,
        event_type=event_type,
        object_ids={"id": obj.get("id"), "type": obj.get("object")},
        state="queued" if job_type else "ignored",
    ))
    try:
        await db.flush()
    except IntegrityError:  # raced a concurrent delivery of the same event
        await db.rollback()
        return False
    if job_type:
        await worker.enqueue(
            db,
            job_type=job_type,
            payload={"event_id": event_id, "event_type": event_type,
                     "object_id": obj.get("id")},
            dedupe_key=f"stripe:{event_id}",
        )
    return True


async def _mark_processed(db: AsyncSession, event_id: str, *, error: str | None = None) -> None:
    row = (
        await db.execute(
            select(ProcessedWebhook).where(
                ProcessedWebhook.provider == "stripe",
                ProcessedWebhook.event_id == event_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        row.state = "error" if error else "processed"
        row.last_error = error
        row.attempts += 1
        row.processed_at = _utcnow()


# ── Shared lookups ───────────────────────────────────────────────────────────

async def _account_for_customer(db: AsyncSession, customer_id: str) -> BillingAccount | None:
    return (
        await db.execute(
            select(BillingAccount).where(BillingAccount.stripe_customer_id == customer_id)
        )
    ).scalar_one_or_none()


async def _binding_by_price(db: AsyncSession, price_id: str, *, livemode: bool) -> StripePriceBinding | None:
    return (
        await db.execute(
            select(StripePriceBinding).where(
                StripePriceBinding.livemode == livemode,
                StripePriceBinding.stripe_price_id == price_id,
            )
        )
    ).scalar_one_or_none()


async def _upsert_subscription_mirror(
    db: AsyncSession, account_id: uuid.UUID, sub: dict, product_key: str | None
) -> StripeSubscription:
    row = await db.get(StripeSubscription, account_id)
    if row is None:
        row = StripeSubscription(
            account_id=account_id,
            stripe_subscription_id=sub["id"],
            product_key=product_key or "",
            status=sub["status"],
        )
        db.add(row)
    row.stripe_subscription_id = sub["id"]
    if product_key:
        row.product_key = product_key
    row.status = sub["status"]
    price = ((sub.get("items") or {}).get("data") or [{}])[0].get("price") or {}
    row.stripe_price_id = price.get("id") or row.stripe_price_id
    row.current_period_start = _ts(sub.get("current_period_start"))
    row.current_period_end = _ts(sub.get("current_period_end"))
    row.cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
    await db.flush()
    return row


def _skip(event_id: str, why: str) -> dict:
    log.warning("stripe event %s skipped: %s", event_id, why)
    return {"granted": False, "skipped": why}


# ── invoice.paid → subscription grant lots ───────────────────────────────────

def _invoice_product_line(invoice: dict) -> dict | None:
    """The single subscription line. Multi-line invoices (proration debris)
    are rejected — plan changes are code-owned and never prorate."""
    lines = (invoice.get("lines") or {}).get("data") or []
    return lines[0] if len(lines) == 1 else None


async def grant_from_paid_invoice(db: AsyncSession, gw: StripeGateway, event_id: str, invoice_id: str) -> dict:
    invoice = await gw.get(f"/v1/invoices/{invoice_id}")

    # Proof-of-money gates — each one grants nothing when it fails.
    if invoice.get("status") != "paid":
        return _skip(event_id, f"invoice status {invoice.get('status')!r}")
    if invoice.get("paid_out_of_band"):
        return _skip(event_id, "paid out of band")
    if not invoice.get("payment_intent") and not invoice.get("charge"):
        return _skip(event_id, "no payment source")
    if invoice.get("currency") != "usd":
        return _skip(event_id, f"currency {invoice.get('currency')!r}")
    if (invoice.get("amount_paid") or 0) <= 0:
        return _skip(event_id, "zero-value invoice")
    sub_id = invoice.get("subscription")
    if not sub_id:
        return _skip(event_id, "not a subscription invoice")
    line = _invoice_product_line(invoice)
    if line is None:
        return _skip(event_id, "expected exactly one invoice line")
    pretax = line.get("amount") or 0
    if pretax <= 0:
        return _skip(event_id, "nonpositive pretax line amount")

    account = await _account_for_customer(db, invoice.get("customer") or "")
    if account is None:
        return _skip(event_id, f"unknown customer {invoice.get('customer')!r}")

    price_id = ((line.get("price") or {}).get("id")) or ""
    binding = await _binding_by_price(db, price_id, livemode=gw.livemode)
    if binding is None:
        return _skip(event_id, f"no binding for price {price_id!r}")

    # The buyer's assigned catalog at invoice time is authoritative for the
    # lot math (002 amendment: renewal migration honors the recorded intent).
    version_id, config = await rating.resolve_commercial_version(
        db, account.account_id, _utcnow()
    )
    product = next(
        (p for p in config.get("products") or [] if p["key"] == binding.product_key),
        None,
    )
    if product is None or product.get("kind") != "subscription":
        return _skip(event_id, f"product {binding.product_key!r} not in assigned catalog")
    if pretax != product["price_usd_cents"]:
        return _skip(
            event_id,
            f"pretax {pretax} != catalog {product['price_usd_cents']} for {product['key']}",
        )

    subscription = await gw.get(f"/v1/subscriptions/{sub_id}")
    if subscription.get("status") not in ("active", "trialing", "past_due"):
        return _skip(event_id, f"subscription status {subscription.get('status')!r}")

    period = line.get("period") or {}
    period_start = _ts(period.get("start")) or _utcnow()
    period_end = _ts(period.get("end"))
    ref = f"stripe:{invoice_id}:{product['key']}"
    granted = 0
    lots = 0

    if product.get("interval") == "year":
        # Twelve monthly paid lots (lot 0 active now, the rest scheduled),
        # bonus lots on the same boundaries, one gift lot for the full year.
        monthly_paid = product["monthly_paid_lot_credits"]
        monthly_bonus = product.get("monthly_bonus_lot_credits") or 0
        boundaries = [add_months_clamped(period_start, i) for i in range(12)]
        boundaries.append(period_end or add_months_clamped(period_start, 12))
        for i in range(12):
            await ledger.create_grant(
                db,
                account_id=account.account_id,
                source_type="subscription_paid",
                source_key=f"{ref}:paid:{i}",
                credits=monthly_paid,
                visible_category="paid",
                effective_at=boundaries[i],
                expires_at=boundaries[i + 1],
                cash_paid_micro_usd=monthly_paid * 10_000,
                stripe_ref=invoice_id,
                actor="stripe",
            )
            granted += monthly_paid
            lots += 1
            if monthly_bonus > 0:
                await ledger.create_grant(
                    db,
                    account_id=account.account_id,
                    source_type="subscription_bonus",
                    source_key=f"{ref}:bonus:{i}",
                    credits=monthly_bonus,
                    visible_category="bonus",
                    effective_at=boundaries[i],
                    expires_at=boundaries[i + 1],
                    stripe_ref=invoice_id,
                    actor="stripe",
                )
                granted += monthly_bonus
                lots += 1
        gift = product.get("yearly_gift_credits") or 0
        if gift > 0:
            await ledger.create_grant(
                db,
                account_id=account.account_id,
                source_type="gift",
                source_key=f"{ref}:gift:0",
                credits=gift,
                visible_category="gift",
                effective_at=period_start,
                expires_at=boundaries[12],
                stripe_ref=invoice_id,
                actor="stripe",
            )
            granted += gift
            lots += 1
    else:
        await ledger.create_grant(
            db,
            account_id=account.account_id,
            source_type="subscription_paid",
            source_key=f"{ref}:paid:0",
            credits=product["paid_credits"],
            visible_category="paid",
            effective_at=period_start,
            expires_at=period_end,
            cash_paid_micro_usd=pretax * 10_000,
            stripe_ref=invoice_id,
            actor="stripe",
        )
        granted += product["paid_credits"]
        lots += 1
        if (product.get("bonus_credits") or 0) > 0:
            await ledger.create_grant(
                db,
                account_id=account.account_id,
                source_type="subscription_bonus",
                source_key=f"{ref}:bonus:0",
                credits=product["bonus_credits"],
                visible_category="bonus",
                effective_at=period_start,
                expires_at=period_end,
                stripe_ref=invoice_id,
                actor="stripe",
            )
            granted += product["bonus_credits"]
            lots += 1

    # Payment-level accumulator for refunds/disputes (idempotent on ref).
    payment_ref = f"invoice:{invoice_id}"
    existing_payment = (
        await db.execute(select(StripePayment).where(StripePayment.payment_ref == payment_ref))
    ).scalar_one_or_none()
    if existing_payment is None:
        charge = invoice.get("charge")
        db.add(StripePayment(
            account_id=account.account_id,
            payment_ref=payment_ref,
            kind="subscription",
            product_key=product["key"],
            commercial_pricing_version_id=version_id,
            currency="usd",
            pretax_amount_cents=pretax,
            tax_amount_cents=invoice.get("tax") or 0,
            granted_credits=granted,
            stripe_charge_id=charge if isinstance(charge, str) else (charge or {}).get("id"),
        ))

    # Successful payment clears dunning and refreshes the mirror.
    row = await _upsert_subscription_mirror(db, account.account_id, subscription, product["key"])
    row.payment_action_required = False
    row.next_payment_retry_at = None
    if account.billing_status == "past_due":
        account.billing_status = "active"
    await db.flush()
    return {"granted": True, "credits": granted, "lots": lots, "product": product["key"]}


# ── checkout.session.completed → top-up grant ────────────────────────────────

async def grant_from_topup_checkout(db: AsyncSession, gw: StripeGateway, event_id: str, session_id: str) -> dict:
    session = await gw.get(f"/v1/checkout/sessions/{session_id}")
    if session.get("mode") != "payment":
        return _skip(event_id, "not a payment-mode session")  # subs grant via invoice.paid
    if session.get("payment_status") != "paid":
        return _skip(event_id, f"payment_status {session.get('payment_status')!r}")
    pi_id = session.get("payment_intent")
    if not pi_id:
        return _skip(event_id, "no payment intent")
    pi = await gw.get(f"/v1/payment_intents/{pi_id}")
    if pi.get("status") != "succeeded":
        return _skip(event_id, f"payment intent status {pi.get('status')!r}")
    if pi.get("currency") != "usd":
        return _skip(event_id, f"currency {pi.get('currency')!r}")

    metadata = pi.get("metadata") or {}
    account = await _account_for_customer(db, session.get("customer") or "")
    if account is None:
        return _skip(event_id, f"unknown customer {session.get('customer')!r}")
    if metadata.get("luna_account_id") != str(account.account_id):
        return _skip(event_id, "metadata account mismatch")

    product_key = metadata.get("luna_product_key") or ""
    _, config = await rating.resolve_commercial_version(db, account.account_id, _utcnow())
    product = next(
        (p for p in config.get("products") or []
         if p["key"] == product_key and p.get("kind") == "topup"),
        None,
    )
    if product is None:
        return _skip(event_id, f"unknown top-up product {product_key!r}")
    amount = pi.get("amount_received") or 0
    if amount != product["price_usd_cents"]:
        return _skip(event_id, f"amount {amount} != catalog {product['price_usd_cents']}")
    expected = int(metadata.get("luna_expected_credits") or 0)
    if expected and expected != product["paid_credits"]:
        return _skip(event_id, "expected credits drifted from catalog")

    await ledger.create_grant(
        db,
        account_id=account.account_id,
        source_type="topup",
        source_key=f"stripe:{pi_id}:{product_key}:paid:0",
        credits=product["paid_credits"],
        visible_category="topup",
        effective_at=_utcnow(),
        expires_at=None,  # top-ups never expire
        cash_paid_micro_usd=amount * 10_000,
        stripe_ref=pi_id,
        actor="stripe",
    )
    payment_ref = f"pi:{pi_id}"
    existing_payment = (
        await db.execute(select(StripePayment).where(StripePayment.payment_ref == payment_ref))
    ).scalar_one_or_none()
    if existing_payment is None:
        charge = pi.get("latest_charge")
        db.add(StripePayment(
            account_id=account.account_id,
            payment_ref=payment_ref,
            kind="topup",
            product_key=product_key,
            currency="usd",
            pretax_amount_cents=amount,
            granted_credits=product["paid_credits"],
            stripe_charge_id=charge if isinstance(charge, str) else (charge or {}).get("id"),
        ))
    await db.flush()
    return {"granted": True, "credits": product["paid_credits"], "product": product_key}


# ── invoice.payment_failed → dunning state (no grants, no grace credits) ─────

async def mark_invoice_failed(db: AsyncSession, gw: StripeGateway, event_id: str, invoice_id: str) -> dict:
    """A failed renewal grants nothing and flips billing to past_due.
    Existing lots keep expiring normally; hosting's renewal sweep enforces
    payment_due when the wallet can no longer cover hosting. Recovery is a
    later verified payment (grant_from_paid_invoice clears the state)."""
    invoice = await gw.get(f"/v1/invoices/{invoice_id}")
    sub_id = invoice.get("subscription")
    if not sub_id:
        return _skip(event_id, "not a subscription invoice")
    account = await _account_for_customer(db, invoice.get("customer") or "")
    if account is None:
        return _skip(event_id, f"unknown customer {invoice.get('customer')!r}")

    # requires_action means the bank wants 3DS/SCA from the customer — the
    # UI shows a "finish payment" banner instead of a generic retry notice.
    action_required = False
    pi_id = invoice.get("payment_intent")
    if pi_id:
        pi = await gw.get(f"/v1/payment_intents/{pi_id}")
        action_required = pi.get("status") in ("requires_action", "requires_payment_method")

    subscription = await gw.get(f"/v1/subscriptions/{sub_id}")
    row = await _upsert_subscription_mirror(db, account.account_id, subscription, None)
    row.payment_action_required = action_required
    row.next_payment_retry_at = _ts(invoice.get("next_payment_attempt"))
    account.billing_status = "past_due"
    await db.flush()
    return {
        "granted": False,
        "billing_status": "past_due",
        "payment_action_required": action_required,
    }


# ── subscription lifecycle mirror ────────────────────────────────────────────

async def sync_subscription(db: AsyncSession, gw: StripeGateway, event_id: str, sub_id: str) -> dict:
    sub = await gw.get(f"/v1/subscriptions/{sub_id}")
    account = await _account_for_customer(db, sub.get("customer") or "")
    if account is None:
        return _skip(event_id, f"unknown customer {sub.get('customer')!r}")
    price_id = ((sub.get("items") or {}).get("data") or [{}])[0].get("price", {}).get("id")
    binding = await _binding_by_price(db, price_id, livemode=gw.livemode) if price_id else None
    row = await _upsert_subscription_mirror(
        db, account.account_id, sub, binding.product_key if binding else None
    )
    return {"status": row.status, "product": row.product_key}


# ── worker handler plumbing ──────────────────────────────────────────────────

def _handler(fn):
    """Adapt a (db, gw, event_id, object_id) coroutine to a worker handler:
    own gateway lifecycle, processed/error stamping on the webhook row."""

    async def run(db: AsyncSession, job: BillingJob) -> dict | None:
        event_id = job.payload["event_id"]
        object_id = job.payload.get("object_id")
        if not object_id:
            await _mark_processed(db, event_id, error="event carried no object id")
            return {"skipped": "no object id"}
        gw = _gateway()
        try:
            result = await fn(db, gw, event_id, object_id)
        finally:
            await gw.aclose()
        await _mark_processed(db, event_id)
        return result

    return run


# Registered at import time, like the rollout/hosting handlers.
worker.register_handler("stripe.invoice_paid", _handler(grant_from_paid_invoice))
worker.register_handler("stripe.checkout_completed", _handler(grant_from_topup_checkout))
worker.register_handler("stripe.subscription_sync", _handler(sync_subscription))
worker.register_handler("stripe.invoice_failed", _handler(mark_invoice_failed))
worker.register_handler("stripe.charge_refunded", _handler(stripe_clawback.handle_charge_refunded))
worker.register_handler("stripe.dispute", _handler(stripe_clawback.handle_dispute))
