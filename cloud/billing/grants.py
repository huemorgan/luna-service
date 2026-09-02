"""Trial and gift grants + per-Luna limit bootstrap (039/005).

Amounts always come from the account's assigned commercial version
(`config.trial` / `config.migration_gift` / `gift_default_days`) — never from
constants — so the admin changes them by publishing a version.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing import ledger, rating
from cloud.billing.models import AgentCreditLimit, CreditGrant

log = logging.getLogger(__name__)

# Grant source_types that mean the account has paid us money — an account
# with none of these is a trial account.
PAID_SOURCE_TYPES = ("subscription_paid", "subscription_bonus", "topup")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def account_config(
    session: AsyncSession, account_id: uuid.UUID, now: datetime | None = None
) -> dict:
    """The assigned commercial version's config for this account, now."""
    _, config = await rating.resolve_commercial_version(session, account_id, now or _utcnow())
    return config


async def is_trial_account(session: AsyncSession, account_id: uuid.UUID) -> bool:
    """Trial = the account has never received a paid grant lot."""
    row = (
        await session.execute(
            select(CreditGrant.id)
            .where(
                CreditGrant.account_id == account_id,
                CreditGrant.source_type.in_(PAID_SOURCE_TYPES),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is None


def _email_domain(email: str | None) -> str | None:
    """Lowercased domain of an email address, or None."""
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[1].strip().lower() or None


async def grant_trial_gift(
    session: AsyncSession,
    account_id: uuid.UUID,
    *,
    email: str | None = None,
    now: datetime | None = None,
) -> CreditGrant | None:
    """Issue the one-time trial gift from the assigned version's config.

    When the signup email has an entry in ``trial.email_gifts`` (individual
    offers), or its domain one in ``trial.domain_gifts`` (partner offers,
    e.g. monday.com), that entry's amount/expiry replaces the standard trial
    gift — still one lot, same idempotency key. The email match wins over
    the domain match.

    Idempotent via source_key ``trial:{account_id}`` — concurrent signup
    callbacks issue exactly one gift. Returns None when the config defines no
    trial gift. Raises RatingUnavailable on an unseeded billing store; the
    signup hook degrades that to a warning.
    """
    now = now or _utcnow()
    config = await account_config(session, account_id, now)
    trial = config.get("trial") or {}
    credits = trial.get("gift_credits") or 0
    days = trial.get("days") or 28
    reason = "trial gift"
    email_key = (email or "").strip().lower()
    domain = _email_domain(email)
    offer = (trial.get("email_gifts") or {}).get(email_key) if email_key else None
    if offer:
        reason = f"trial gift ({email_key} signup offer)"
    else:
        offer = (trial.get("domain_gifts") or {}).get(domain) if domain else None
        if offer:
            reason = f"trial gift ({domain} signup offer)"
    if offer:
        credits = offer.get("gift_credits") or 0
        days = offer.get("days") or days
    if credits <= 0:
        return None
    return await ledger.create_grant(
        session,
        account_id=account_id,
        source_type="gift",
        source_key=f"trial:{account_id}",
        credits=credits,
        visible_category="gift",
        effective_at=now,
        expires_at=now + timedelta(days=days),
        actor="system",
        reason=reason,
        now=now,
    )


async def grant_admin_gift(
    session: AsyncSession,
    account_id: uuid.UUID,
    *,
    credits: int,
    expires_days: int | None,
    source_key: str,
    actor: str,
    reason: str,
    now: datetime | None = None,
) -> CreditGrant:
    """Admin-issued gift lot. Caller supplies the idempotency source_key."""
    now = now or _utcnow()
    expires_at = now + timedelta(days=expires_days) if expires_days else None
    return await ledger.create_grant(
        session,
        account_id=account_id,
        source_type="admin",
        source_key=source_key,
        credits=credits,
        visible_category="gift",
        effective_at=now,
        expires_at=expires_at,
        actor=actor,
        reason=reason,
        now=now,
    )


async def apply_trial_agent_limits(
    session: AsyncSession, agent_id: uuid.UUID, config: dict
) -> AgentCreditLimit | None:
    """Write the trial per-Luna day/month caps for a new agent. Insert-only:
    an existing row (customer- or admin-edited) is never overwritten."""
    trial = config.get("trial") or {}
    daily = trial.get("daily_limit_credits")
    monthly = trial.get("monthly_limit_credits")
    if daily is None and monthly is None:
        return None
    existing = await session.get(AgentCreditLimit, agent_id)
    if existing is not None:
        return existing
    row = AgentCreditLimit(
        agent_id=agent_id,
        daily_limit_credits=daily,
        monthly_limit_credits=monthly,
    )
    session.add(row)
    await session.flush()
    return row


def active_luna_cap(config: dict) -> int | None:
    """Trial active-Luna maximum from the version config. None = uncapped."""
    trial = config.get("trial") or {}
    cap = trial.get("active_luna_cap")
    return int(cap) if cap is not None else None
