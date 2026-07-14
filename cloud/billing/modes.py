"""Per-account billing-mode resolution (039/010).

`CLOUD_BILLING_MODE` is global; `billing_accounts.enforcement_override` is a
nullable per-account escalation set by admins during rollout. The effective
mode for an account is the maximum of the two on the ordered scale

    off < observe < shadow < enforce

so an override can only escalate — internal canaries can be enforced while
every customer stays off/observe, and no override can ever weaken the global
mode. Overrides are audited by the admin API (who/when/reason) and stamped
with `enforcement_override_set_at`.

The gateway hot path must not pay a query per request just to learn that no
overrides exist: the override map is cached in-process for a short TTL.
Setting an override invalidates the local cache immediately; other processes
converge within the TTL — rollout steps are human-paced, so seconds of skew
are acceptable and only ever delay an *escalation*, never a block's removal
of service.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing.models import BillingAccount

MODES = ("off", "observe", "shadow", "enforce")
_RANK = {mode: rank for rank, mode in enumerate(MODES)}

# An override of "off" is meaningless (max() would ignore it) — clearing the
# override is expressed as NULL, so only escalating values are storable.
OVERRIDE_MODES = ("observe", "shadow", "enforce")

OVERRIDE_CACHE_TTL_SECONDS = 15.0

_cache: dict[uuid.UUID, str] | None = None
_cache_at: float = 0.0


def combine(global_mode: str, override: str | None) -> str:
    """Effective mode: the stronger of the global mode and the override."""
    if override is None:
        return global_mode
    return global_mode if _RANK[global_mode] >= _RANK[override] else override


def invalidate_override_cache() -> None:
    global _cache, _cache_at
    _cache = None
    _cache_at = 0.0


async def override_map(session: AsyncSession) -> dict[uuid.UUID, str]:
    """All current overrides, TTL-cached in-process for the gateway hot path."""
    global _cache, _cache_at
    now = time.monotonic()
    if _cache is not None and now - _cache_at < OVERRIDE_CACHE_TTL_SECONDS:
        return _cache
    rows = await session.execute(
        select(BillingAccount.account_id, BillingAccount.enforcement_override).where(
            BillingAccount.enforcement_override.is_not(None)
        )
    )
    _cache = {account_id: mode for account_id, mode in rows}
    _cache_at = now
    return _cache


async def account_override(session: AsyncSession, account_id: uuid.UUID) -> str | None:
    """The account's override, read fresh (no cache) — for billing-layer
    decisions that already sit on a DB round-trip."""
    row = await session.execute(
        select(BillingAccount.enforcement_override).where(
            BillingAccount.account_id == account_id
        )
    )
    return row.scalar_one_or_none()


async def effective_mode(
    session: AsyncSession, account_id: uuid.UUID, global_mode: str
) -> str:
    return combine(global_mode, await account_override(session, account_id))


async def set_override(
    session: AsyncSession, account_id: uuid.UUID, mode: str | None
) -> BillingAccount:
    """Set or clear (mode=None) the account's enforcement override. The
    caller writes the audit row and supplies the reason; this only mutates
    state and stamps the effective timestamp."""
    if mode is not None and mode not in OVERRIDE_MODES:
        raise ValueError(f"override must be one of {OVERRIDE_MODES} or None, got {mode!r}")
    from cloud.billing import ledger

    row = await ledger.ensure_billing_account(session, account_id)
    row.enforcement_override = mode
    row.enforcement_override_set_at = datetime.now(timezone.utc)
    await session.flush()
    invalidate_override_cache()
    return row
