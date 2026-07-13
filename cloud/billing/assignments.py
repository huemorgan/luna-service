"""Commercial pricing assignments and rollouts (039/002).

Assignments form a gapless, non-overlapping chain of effective intervals per
account: exactly one interval is open (`ends_at IS NULL`), each new assignment
closes the previous interval at its own `effective_at`, and effective times
are strictly increasing. The service enforces this under the billing-account
row lock; on Postgres a gist exclusion constraint (migration 0003) is the
backstop.

The new-account default is effective-dated: the newest `new_accounts` or
`all_accounts` rollout whose `effective_at` has passed names the version new
accounts receive; before any rollout exists it falls back to the
highest-numbered published version (the seeded v1).

Rollout execution runs as a durable `billing_outbox` job — never an
in-process task — and is restart-safe: every assignment it creates carries
`audit_ref = "rollout:{id}"`, so a rerun neither skips nor duplicates
accounts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing.ledger import ensure_billing_account, lock_billing_account
from cloud.billing.models import (
    BillingAccount,
    CommercialPricingAssignment,
    CommercialPricingRollout,
    CommercialPricingVersion,
)
from cloud.billing.worker import enqueue, register_handler
from cloud.db.models import Account


class AssignmentError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _require_published(
    session: AsyncSession, version_id: uuid.UUID
) -> CommercialPricingVersion:
    version = await session.get(CommercialPricingVersion, version_id)
    if version is None:
        raise AssignmentError("version not found")
    if version.status != "published":
        raise AssignmentError(f"only published versions can be assigned (status={version.status})")
    return version


async def default_version_id(session: AsyncSession, *, now: datetime | None = None) -> uuid.UUID:
    """The version a newly created account is assigned right now."""
    now = now or _utcnow()
    rollout = (
        await session.execute(
            select(CommercialPricingRollout)
            .where(
                CommercialPricingRollout.audience.in_(("new_accounts", "all_accounts")),
                CommercialPricingRollout.effective_at <= now,
                CommercialPricingRollout.status.in_(("scheduled", "running", "applied", "completed")),
            )
            .order_by(CommercialPricingRollout.effective_at.desc(),
                      CommercialPricingRollout.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if rollout is not None:
        return rollout.commercial_pricing_version_id
    version = (
        await session.execute(
            select(CommercialPricingVersion)
            .where(CommercialPricingVersion.status == "published")
            .order_by(CommercialPricingVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if version is None:
        raise AssignmentError("no published commercial version exists")
    return version.id


async def assignment_for_account_at(
    session: AsyncSession, account_id: uuid.UUID, at: datetime
) -> CommercialPricingAssignment | None:
    return (
        await session.execute(
            select(CommercialPricingAssignment)
            .where(
                CommercialPricingAssignment.account_id == account_id,
                CommercialPricingAssignment.effective_at <= at,
            )
            .order_by(CommercialPricingAssignment.effective_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def version_for_account_at(
    session: AsyncSession, account_id: uuid.UUID, at: datetime
) -> uuid.UUID | None:
    """Authoritative resolution — reads the assignment chain, never the
    `current_assignment_id` cache."""
    assignment = await assignment_for_account_at(session, account_id, at)
    if assignment is None:
        return None
    ends_at = _aware(assignment.ends_at)
    if ends_at is not None and ends_at <= at:
        return None
    return assignment.commercial_pricing_version_id


async def assign_version(
    session: AsyncSession,
    account_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    effective_at: datetime,
    source: str,
    actor_user_id: uuid.UUID | None = None,
    audit_ref: str | None = None,
) -> CommercialPricingAssignment:
    """Append an assignment to the account's chain at `effective_at`.

    The chain is append-only and strictly increasing: history is never edited
    (rollback = scheduling a prior version as a future assignment).
    """
    await _require_published(session, version_id)
    await ensure_billing_account(session, account_id)
    billing = await lock_billing_account(session, account_id)

    effective_at = _aware(effective_at)
    rows = (
        await session.execute(
            select(CommercialPricingAssignment)
            .where(CommercialPricingAssignment.account_id == account_id)
            .order_by(CommercialPricingAssignment.effective_at.desc())
        )
    ).scalars().all()
    latest = rows[0] if rows else None
    if latest is not None:
        latest_effective = _aware(latest.effective_at)
        if latest_effective >= effective_at:
            raise AssignmentError(
                "an assignment at or after this effective time already exists "
                f"({latest_effective.isoformat()})"
            )
        # Close the open interval exactly where the new one starts: no gap,
        # no overlap.
        if latest.ends_at is None:
            latest.ends_at = effective_at

    assignment = CommercialPricingAssignment(
        account_id=account_id,
        commercial_pricing_version_id=version_id,
        effective_at=effective_at,
        source=source,
        actor_user_id=actor_user_id,
        audit_ref=audit_ref,
    )
    session.add(assignment)
    await session.flush()
    if effective_at <= _utcnow():
        billing.current_assignment_id = assignment.id
    await session.flush()
    return assignment


async def assign_new_account(
    session: AsyncSession, account_id: uuid.UUID, *, now: datetime | None = None
) -> CommercialPricingAssignment:
    """Create the billing account and its first assignment (same transaction
    as account creation). Idempotent: an already-assigned account is left
    untouched."""
    now = now or _utcnow()
    await ensure_billing_account(session, account_id)
    existing = (
        await session.execute(
            select(CommercialPricingAssignment)
            .where(CommercialPricingAssignment.account_id == account_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    version_id = await default_version_id(session, now=now)
    return await assign_version(
        session, account_id, version_id,
        effective_at=now, source="new_account_default",
    )


# ── Rollouts ─────────────────────────────────────────────────────────────────

async def create_rollout(
    session: AsyncSession,
    version_id: uuid.UUID,
    *,
    audience: str,
    effective_at: datetime,
    selected_account_ids: list[uuid.UUID] | None = None,
    created_by: uuid.UUID | None = None,
) -> CommercialPricingRollout:
    await _require_published(session, version_id)
    if audience not in ("new_accounts", "all_accounts", "selected_accounts"):
        raise AssignmentError(f"unknown audience {audience!r}")
    if audience == "selected_accounts" and not selected_account_ids:
        raise AssignmentError("selected_accounts rollout requires account IDs")
    if audience != "selected_accounts" and selected_account_ids:
        raise AssignmentError(f"{audience} rollout does not take account IDs")

    rollout = CommercialPricingRollout(
        commercial_pricing_version_id=version_id,
        audience=audience,
        selected_account_ids=[str(a) for a in selected_account_ids] if selected_account_ids else None,
        effective_at=_aware(effective_at),
        # all_accounts additionally records the per-subscription renewal
        # migration intent consumed by 039/007.
        migration_policy="next_renewal",
        status="scheduled",
        created_by=created_by,
    )
    session.add(rollout)
    await session.flush()
    await enqueue(
        session,
        job_type="pricing_rollout",
        payload={"rollout_id": str(rollout.id)},
        run_at=rollout.effective_at,
        dedupe_key=f"pricing_rollout:{rollout.id}",
    )
    return rollout


async def execute_rollout(
    session: AsyncSession, rollout_id: uuid.UUID, *, now: datetime | None = None
) -> CommercialPricingRollout:
    """Apply a due rollout. Restart-safe and idempotent: rerunning resumes
    where the previous run stopped, without duplicate assignments."""
    now = now or _utcnow()
    rollout = await session.get(CommercialPricingRollout, rollout_id)
    if rollout is None:
        raise AssignmentError("rollout not found")
    if rollout.status == "completed":
        return rollout
    effective_at = _aware(rollout.effective_at)
    if effective_at > now:
        raise AssignmentError("rollout is not due yet")
    rollout.status = "running"
    target_version = rollout.commercial_pricing_version_id

    if rollout.audience == "new_accounts":
        # Nothing per-account: from effective_at this rollout *is* the
        # new-account default (see default_version_id). Existing accounts
        # stay pinned.
        rollout.accounts_scheduled = 0
        rollout.status = "completed"
        await session.flush()
        return rollout

    if rollout.audience == "selected_accounts":
        target_ids = [uuid.UUID(a) for a in rollout.selected_account_ids or []]
    else:  # all_accounts — every account that exists at execution time
        target_ids = list(
            (await session.execute(select(Account.id))).scalars().all()
        )
    rollout.accounts_scheduled = len(target_ids)

    audit_ref = f"rollout:{rollout.id}"
    applied = failed = 0
    for account_id in target_ids:
        already = (
            await session.execute(
                select(CommercialPricingAssignment).where(
                    CommercialPricingAssignment.account_id == account_id,
                    CommercialPricingAssignment.audit_ref == audit_ref,
                )
            )
        ).scalar_one_or_none()
        if already is not None:
            applied += 1  # previous run got here — never duplicated
            continue
        current = await version_for_account_at(session, account_id, now)
        if current == target_version:
            # Already governed by the target (e.g. created after effective_at
            # under the updated default) — exactly one assignment, no second.
            applied += 1
            continue
        try:
            await assign_version(
                session, account_id, target_version,
                effective_at=max(effective_at, now), source="global_rollout",
                actor_user_id=rollout.created_by, audit_ref=audit_ref,
            )
            applied += 1
        except AssignmentError:
            # e.g. a manual future assignment exists — surfaced for review,
            # never overwritten.
            failed += 1
    rollout.accounts_applied = applied
    rollout.accounts_failed = failed
    rollout.status = "completed" if failed == 0 else "completed_with_failures"
    await session.flush()
    return rollout


async def _handle_pricing_rollout(session: AsyncSession, job) -> dict:
    rollout = await execute_rollout(session, uuid.UUID(job.payload["rollout_id"]))
    return {
        "status": rollout.status,
        "scheduled": rollout.accounts_scheduled,
        "applied": rollout.accounts_applied,
        "failed": rollout.accounts_failed,
    }


register_handler("pricing_rollout", _handle_pricing_rollout)
