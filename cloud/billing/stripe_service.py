"""039/007 — Stripe customers, checkout sessions, and the Billing Portal.

All money-in STARTS here; none of it FINISHES here. Checkout/portal URLs
are handed to the browser, and credits are granted exclusively by verified
webhook events (stripe_webhooks.py) — never from a success redirect.

Rules enforced:
- one Stripe Customer per account (row lock + Stripe idempotency key);
- checkout creates the FIRST subscription only — plan changes are
  code-owned subscription updates, not new checkouts;
- top-ups come from the account's versioned catalog steps only; metadata
  carries the account, product key, pricing version, expected credits, and
  an unguessable server operation id;
- a catalog/binding price drift blocks checkout before money moves.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing import ledger, rating
from cloud.billing.models import StripePriceBinding, StripeSubscription
from cloud.billing.stripe_gateway import StripeGateway
from cloud.config import Settings, get_settings
from cloud.db.models import Account, User

# Subscription statuses that no longer occupy the account's single slot.
DEAD_SUB_STATUSES = ("canceled", "incomplete_expired")


class CheckoutRejected(Exception):
    """A checkout precondition failed; message is customer-safe."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def product_from_config(config: dict, product_key: str) -> dict | None:
    for p in config.get("products") or []:
        if p["key"] == product_key:
            return p
    return None


async def binding_for(
    db: AsyncSession, product_key: str, *, livemode: bool
) -> StripePriceBinding | None:
    return (
        await db.execute(
            select(StripePriceBinding).where(
                StripePriceBinding.livemode == livemode,
                StripePriceBinding.product_key == product_key,
            )
        )
    ).scalar_one_or_none()


async def _checked_binding(
    db: AsyncSession, product: dict, *, livemode: bool
) -> StripePriceBinding:
    binding = await binding_for(db, product["key"], livemode=livemode)
    if binding is None:
        raise CheckoutRejected("This package is not available for purchase yet")
    if binding.price_usd_cents != product["price_usd_cents"] or (
        binding.interval or None
    ) != (product.get("interval") or None):
        # Catalog moved after binding was attached — fail before money moves.
        raise CheckoutRejected("This package is being updated; try again later")
    return binding


async def ensure_stripe_customer(
    db: AsyncSession, gw: StripeGateway, account: Account, user: User
) -> str:
    """Exactly one Stripe Customer per account: the billing-account row lock
    serializes concurrent creators, and the Stripe idempotency key makes the
    API call itself single-shot even across crashed attempts."""
    ba = await ledger.lock_billing_account(db, account.id)
    if ba.stripe_customer_id:
        return ba.stripe_customer_id
    customer = await gw.post(
        "/v1/customers",
        {
            "name": account.name,
            "email": user.email,
            "metadata": {"luna_account_id": str(account.id)},
        },
        idempotency_key=f"luna-customer-{account.id}",
    )
    ba.stripe_customer_id = customer["id"]
    await db.flush()
    return customer["id"]


async def current_subscription(
    db: AsyncSession, account_id: uuid.UUID
) -> StripeSubscription | None:
    sub = await db.get(StripeSubscription, account_id)
    if sub is None or sub.status in DEAD_SUB_STATUSES:
        return None
    return sub


async def create_subscription_checkout(
    db: AsyncSession,
    gw: StripeGateway,
    account: Account,
    user: User,
    product_key: str,
    *,
    settings: Settings | None = None,
) -> str:
    """Checkout URL for the account's FIRST subscription."""
    s = settings or get_settings()
    version_id, config = await rating.resolve_commercial_version(
        db, account.id, _utcnow()
    )
    product = product_from_config(config, product_key)
    if product is None or product.get("kind") != "subscription":
        raise CheckoutRejected("Unknown subscription package")
    if await current_subscription(db, account.id) is not None:
        raise CheckoutRejected(
            "This account already has a subscription — change plans instead"
        )
    binding = await _checked_binding(db, product, livemode=gw.livemode)
    customer_id = await ensure_stripe_customer(db, gw, account, user)
    operation_id = uuid.uuid4().hex
    metadata = {
        "luna_account_id": str(account.id),
        "luna_product_key": product_key,
        "luna_pricing_version": str(version_id),
        "luna_operation_id": operation_id,
    }
    session = await gw.post(
        "/v1/checkout/sessions",
        {
            "mode": "subscription",
            "customer": customer_id,
            "client_reference_id": str(account.id),
            "line_items": [{"price": binding.stripe_price_id, "quantity": 1}],
            "success_url": f"{s.base_url}/billing?checkout=success",
            "cancel_url": f"{s.base_url}/billing?checkout=cancelled",
            "metadata": metadata,
            "subscription_data": {"metadata": metadata},
        },
        idempotency_key=f"luna-checkout-sub-{operation_id}",
    )
    return session["url"]


async def create_topup_checkout(
    db: AsyncSession,
    gw: StripeGateway,
    account: Account,
    user: User,
    amount_usd_cents: int,
    *,
    settings: Settings | None = None,
) -> str:
    """Checkout URL for a fixed catalog top-up step. The browser picks a
    step; the server resolves product, price, and expected credits — an
    arbitrary amount can never be submitted."""
    s = settings or get_settings()
    version_id, config = await rating.resolve_commercial_version(
        db, account.id, _utcnow()
    )
    steps = config.get("topup_steps_usd_cents") or []
    if amount_usd_cents not in steps:
        raise CheckoutRejected("Unknown top-up amount")
    product = next(
        (
            p
            for p in config.get("products") or []
            if p.get("kind") == "topup" and p["price_usd_cents"] == amount_usd_cents
        ),
        None,
    )
    if product is None:
        raise CheckoutRejected("Unknown top-up amount")
    binding = await _checked_binding(db, product, livemode=gw.livemode)
    customer_id = await ensure_stripe_customer(db, gw, account, user)
    operation_id = uuid.uuid4().hex
    metadata = {
        "luna_account_id": str(account.id),
        "luna_product_key": product["key"],
        "luna_pricing_version": str(version_id),
        "luna_expected_credits": str(product["paid_credits"]),
        "luna_operation_id": operation_id,
    }
    session = await gw.post(
        "/v1/checkout/sessions",
        {
            "mode": "payment",
            "customer": customer_id,
            "client_reference_id": str(account.id),
            "line_items": [{"price": binding.stripe_price_id, "quantity": 1}],
            "success_url": f"{s.base_url}/billing?topup=success",
            "cancel_url": f"{s.base_url}/billing?topup=cancelled",
            "metadata": metadata,
            "payment_intent_data": {"metadata": metadata},
        },
        idempotency_key=f"luna-checkout-topup-{operation_id}",
    )
    return session["url"]


async def create_portal_session(
    db: AsyncSession,
    gw: StripeGateway,
    account: Account,
    user: User,
    *,
    settings: Settings | None = None,
) -> str:
    s = settings or get_settings()
    customer_id = await ensure_stripe_customer(db, gw, account, user)
    session = await gw.post(
        "/v1/billing_portal/sessions",
        {"customer": customer_id, "return_url": f"{s.base_url}/billing"},
    )
    return session["url"]
