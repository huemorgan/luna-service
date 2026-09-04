"""Coupon codes (plan 102): admin-issued single-use credit coupons.

A coupon carries a credit count. Redemption (customer billing page) issues
one gift grant lot and permanently stamps the coupon with who redeemed it;
the grant's source_key ``coupon:{id}`` makes redemption idempotent at the
ledger even if the row-lock race were ever lost.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing import ledger
from cloud.billing.grants import account_config
from cloud.billing.models import Coupon, CreditGrant

# No 0/O/1/I — codes get read aloud and retyped.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class CouponError(ValueError):
    """Invalid coupon operation (unknown/used code, bad create input)."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def generate_code() -> str:
    body = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return f"LUNA-{body[:4]}-{body[4:]}"


def normalize_code(code: str) -> str:
    return code.strip().upper()


async def create_coupon(
    session: AsyncSession,
    *,
    credits: int,
    code: str | None = None,
    expires_days: int | None = None,
    reason: str,
    created_by: uuid.UUID | None = None,
) -> Coupon:
    if not isinstance(credits, int) or isinstance(credits, bool) or credits <= 0:
        raise CouponError("credits must be a positive integer")
    if expires_days is not None and expires_days <= 0:
        raise CouponError("expires_days must be positive when set")
    code = normalize_code(code) if code else generate_code()
    if not code:
        raise CouponError("code must not be empty")
    existing = (
        await session.execute(select(Coupon.id).where(Coupon.code == code))
    ).scalar_one_or_none()
    if existing is not None:
        raise CouponError(f"coupon code {code!r} already exists")
    coupon = Coupon(
        code=code,
        credits=credits,
        expires_days=expires_days,
        reason=reason,
        created_by=created_by,
    )
    session.add(coupon)
    await session.flush()
    return coupon


async def create_coupons(
    session: AsyncSession,
    *,
    credits: int,
    count: int,
    code: str | None = None,
    expires_days: int | None = None,
    reason: str,
    created_by: uuid.UUID | None = None,
) -> list[Coupon]:
    """Batch mint: `count` coupons sharing credits/expiry/reason. A custom
    code only makes sense for a single coupon."""
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise CouponError("count must be a positive integer")
    if count > 1 and code:
        raise CouponError("a custom code cannot be used with count > 1")
    return [
        await create_coupon(
            session, credits=credits, code=code, expires_days=expires_days,
            reason=reason, created_by=created_by,
        )
        for _ in range(count)
    ]


async def set_sent(
    session: AsyncSession,
    coupon_id: uuid.UUID,
    *,
    sent: bool,
    now: datetime | None = None,
) -> Coupon:
    """Admin bookkeeping: mark a coupon as handed out (or undo a misclick).
    Redeemed coupons are frozen."""
    coupon = await session.get(Coupon, coupon_id)
    if coupon is None:
        raise CouponError("invalid_code")
    if coupon.redeemed_at is not None:
        raise CouponError("coupon_used")
    coupon.sent_at = (now or _utcnow()) if sent else None
    await session.flush()
    return coupon


async def redeem_coupon(
    session: AsyncSession,
    *,
    code: str,
    account_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> tuple[Coupon, CreditGrant]:
    """Redeem onto the account; raises CouponError("invalid_code") /
    CouponError("coupon_used"). Locks the coupon row so concurrent submits
    of the same code serialize."""
    now = now or _utcnow()
    coupon = (
        await session.execute(
            select(Coupon).where(Coupon.code == normalize_code(code)).with_for_update()
        )
    ).scalar_one_or_none()
    if coupon is None:
        raise CouponError("invalid_code")
    if coupon.redeemed_at is not None:
        raise CouponError("coupon_used")

    config = await account_config(session, account_id, now)
    days = coupon.expires_days or config.get("gift_default_days") or 90
    await ledger.ensure_billing_account(session, account_id)
    grant = await ledger.create_grant(
        session,
        account_id=account_id,
        source_type="gift",
        source_key=f"coupon:{coupon.id}",
        credits=coupon.credits,
        visible_category="gift",
        effective_at=now,
        expires_at=now + timedelta(days=days),
        actor=f"user:{user_id}",
        reason=f"coupon {coupon.code}",
        now=now,
    )
    coupon.redeemed_at = now
    coupon.redeemed_by_account_id = account_id
    coupon.redeemed_by_user_id = user_id
    coupon.grant_id = grant.id
    await session.flush()
    return coupon, grant


async def delete_coupon(session: AsyncSession, coupon_id: uuid.UUID) -> Coupon:
    """Delete an unredeemed coupon. Redeemed coupons are permanent records."""
    coupon = await session.get(Coupon, coupon_id)
    if coupon is None:
        raise CouponError("invalid_code")
    if coupon.redeemed_at is not None:
        raise CouponError("coupon_used")
    await session.delete(coupon)
    await session.flush()
    return coupon
