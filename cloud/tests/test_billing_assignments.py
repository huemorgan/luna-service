"""039/002 — assignment chain, new-account default, rollouts, outbox execution."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import cloud.billing.assignments  # noqa: F401 — registers the rollout handler
from cloud.billing.assignments import (
    AssignmentError,
    assign_new_account,
    assign_version,
    create_rollout,
    default_version_id,
    execute_rollout,
    version_for_account_at,
)
from cloud.billing.models import BillingAccount, BillingJob, CommercialPricingAssignment
from cloud.billing.seed import commercial_v1_config, seed_commercial_v1
from cloud.billing.versions import clone_version, publish_version, update_draft
from cloud.billing.worker import run_once
from cloud.db.models import Account, User

pytestmark = pytest.mark.asyncio

# Fixed in the past relative to the real clock — assign_version's cache
# update and the worker's due check compare against wall time (039/001
# learning: never anchor test times at-or-after utcnow).
NOW = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


async def _mk_account(db, slug: str) -> Account:
    user = User(google_sub=f"sub-{slug}", email=f"{slug}@example.com")
    db.add(user)
    await db.flush()
    account = Account(slug=slug, name=slug, created_by=user.id)
    db.add(account)
    await db.flush()
    return account


async def _publish_v2(db, v1):
    """Clone v1 into a valid, distinguishable published v2."""
    draft = await clone_version(db, v1.id, name="v2")
    config = commercial_v1_config()
    config["trial"]["gift_credits"] = 2_000
    await update_draft(db, draft.id, config=config)
    return await publish_version(db, draft.id)


# ── Default resolution ───────────────────────────────────────────────────────

async def test_default_falls_back_to_highest_published(db_session):
    with pytest.raises(AssignmentError, match="no published"):
        await default_version_id(db_session, now=NOW)
    v1 = await seed_commercial_v1(db_session)
    assert await default_version_id(db_session, now=NOW) == v1.id
    v2 = await _publish_v2(db_session, v1)
    assert await default_version_id(db_session, now=NOW) == v2.id


async def test_default_prefers_effective_rollout(db_session):
    v1 = await seed_commercial_v1(db_session)
    v2 = await _publish_v2(db_session, v1)
    # A future new_accounts rollout for v1 does not apply yet…
    await create_rollout(
        db_session, v1.id, audience="new_accounts",
        effective_at=NOW + timedelta(days=1),
    )
    assert await default_version_id(db_session, now=NOW) == v2.id
    # …but once effective_at passes, it names the default.
    assert await default_version_id(
        db_session, now=NOW + timedelta(days=2)
    ) == v1.id


# ── New-account assignment ───────────────────────────────────────────────────

async def test_assign_new_account_idempotent(db_session):
    v1 = await seed_commercial_v1(db_session)
    account = await _mk_account(db_session, "acme")
    first = await assign_new_account(db_session, account.id, now=NOW)
    assert first.commercial_pricing_version_id == v1.id
    assert first.source == "new_account_default"
    again = await assign_new_account(db_session, account.id, now=NOW + timedelta(hours=1))
    assert again.id == first.id  # untouched, no second row
    billing = (await db_session.execute(
        select(BillingAccount).where(BillingAccount.account_id == account.id)
    )).scalar_one()
    assert billing.current_assignment_id == first.id


# ── Chain semantics ──────────────────────────────────────────────────────────

async def test_chain_gapless_and_append_only(db_session):
    v1 = await seed_commercial_v1(db_session)
    v2 = await _publish_v2(db_session, v1)
    account = await _mk_account(db_session, "acme")
    a1 = await assign_version(
        db_session, account.id, v1.id, effective_at=NOW, source="manual_test"
    )
    assert a1.ends_at is None
    a2 = await assign_version(
        db_session, account.id, v2.id,
        effective_at=NOW + timedelta(days=10), source="manual_test",
    )
    # Old interval closed exactly where the new one starts: no gap, no overlap.
    assert a1.ends_at == a2.effective_at
    assert a2.ends_at is None
    # History reads resolve by interval.
    assert await version_for_account_at(db_session, account.id, NOW + timedelta(days=1)) == v1.id
    assert await version_for_account_at(db_session, account.id, NOW + timedelta(days=11)) == v2.id
    assert await version_for_account_at(db_session, account.id, NOW - timedelta(days=1)) is None


async def test_overlapping_or_backdated_assignment_rejected(db_session):
    v1 = await seed_commercial_v1(db_session)
    v2 = await _publish_v2(db_session, v1)
    account = await _mk_account(db_session, "acme")
    await assign_version(db_session, account.id, v1.id, effective_at=NOW, source="manual_test")
    for bad_at in (NOW, NOW - timedelta(days=1)):
        with pytest.raises(AssignmentError, match="at or after"):
            await assign_version(
                db_session, account.id, v2.id, effective_at=bad_at, source="manual_test"
            )
    # Exactly one open interval remains.
    open_rows = (await db_session.execute(
        select(CommercialPricingAssignment).where(
            CommercialPricingAssignment.account_id == account.id,
            CommercialPricingAssignment.ends_at.is_(None),
        )
    )).scalars().all()
    assert len(open_rows) == 1


async def test_only_published_versions_assignable(db_session):
    v1 = await seed_commercial_v1(db_session)
    draft = await clone_version(db_session, v1.id, name="draft")
    account = await _mk_account(db_session, "acme")
    with pytest.raises(AssignmentError, match="published"):
        await assign_version(
            db_session, account.id, draft.id, effective_at=NOW, source="manual_test"
        )


async def test_future_assignment_does_not_update_cache(db_session):
    v1 = await seed_commercial_v1(db_session)
    v2 = await _publish_v2(db_session, v1)
    account = await _mk_account(db_session, "acme")
    current = await assign_new_account(db_session, account.id)
    future_at = datetime.now(timezone.utc) + timedelta(days=30)
    await assign_version(
        db_session, account.id, v2.id, effective_at=future_at, source="manual_test"
    )
    billing = (await db_session.execute(
        select(BillingAccount).where(BillingAccount.account_id == account.id)
    )).scalar_one()
    assert billing.current_assignment_id == current.id  # still on v1 until due


# ── Rollouts ─────────────────────────────────────────────────────────────────

async def test_rollout_audience_validation(db_session):
    v1 = await seed_commercial_v1(db_session)
    with pytest.raises(AssignmentError, match="audience"):
        await create_rollout(db_session, v1.id, audience="everyone", effective_at=NOW)
    with pytest.raises(AssignmentError, match="requires account IDs"):
        await create_rollout(db_session, v1.id, audience="selected_accounts", effective_at=NOW)
    with pytest.raises(AssignmentError, match="does not take account IDs"):
        await create_rollout(
            db_session, v1.id, audience="all_accounts", effective_at=NOW,
            selected_account_ids=[uuid.uuid4()],
        )


async def test_rollout_enqueues_durable_job(db_session):
    v1 = await seed_commercial_v1(db_session)
    rollout = await create_rollout(
        db_session, v1.id, audience="new_accounts", effective_at=NOW
    )
    job = (await db_session.execute(
        select(BillingJob).where(BillingJob.dedupe_key == f"pricing_rollout:{rollout.id}")
    )).scalar_one()
    assert job.job_type == "pricing_rollout"
    assert job.payload == {"rollout_id": str(rollout.id)}


async def test_rollout_not_due_raises(db_session):
    v1 = await seed_commercial_v1(db_session)
    rollout = await create_rollout(
        db_session, v1.id, audience="all_accounts", effective_at=NOW + timedelta(days=1)
    )
    with pytest.raises(AssignmentError, match="not due"):
        await execute_rollout(db_session, rollout.id, now=NOW)


async def test_all_accounts_rollout_moves_everyone(db_session):
    v1 = await seed_commercial_v1(db_session)
    a = await _mk_account(db_session, "a")
    b = await _mk_account(db_session, "b")
    await assign_new_account(db_session, a.id, now=NOW)
    await assign_new_account(db_session, b.id, now=NOW)
    v2 = await _publish_v2(db_session, v1)
    rollout = await create_rollout(
        db_session, v2.id, audience="all_accounts", effective_at=NOW + timedelta(days=1)
    )
    at = NOW + timedelta(days=1, hours=1)
    done = await execute_rollout(db_session, rollout.id, now=at)
    assert done.status == "completed"
    assert done.accounts_scheduled == 2 and done.accounts_applied == 2
    for acct in (a, b):
        assert await version_for_account_at(db_session, acct.id, at + timedelta(hours=1)) == v2.id
        # History before the rollout still resolves to v1.
        assert await version_for_account_at(db_session, acct.id, NOW + timedelta(hours=1)) == v1.id


async def test_selected_accounts_rollout_targets_only_selection(db_session):
    v1 = await seed_commercial_v1(db_session)
    a = await _mk_account(db_session, "a")
    b = await _mk_account(db_session, "b")
    await assign_new_account(db_session, a.id, now=NOW)
    await assign_new_account(db_session, b.id, now=NOW)
    v2 = await _publish_v2(db_session, v1)
    rollout = await create_rollout(
        db_session, v2.id, audience="selected_accounts",
        effective_at=NOW + timedelta(days=1), selected_account_ids=[a.id],
    )
    at = NOW + timedelta(days=2)
    await execute_rollout(db_session, rollout.id, now=at)
    assert await version_for_account_at(db_session, a.id, at + timedelta(hours=1)) == v2.id
    assert await version_for_account_at(db_session, b.id, at + timedelta(hours=1)) == v1.id


async def test_rollout_rerun_is_idempotent(db_session):
    """Restart safety: a rerun neither duplicates nor skips accounts."""
    v1 = await seed_commercial_v1(db_session)
    a = await _mk_account(db_session, "a")
    b = await _mk_account(db_session, "b")
    await assign_new_account(db_session, a.id, now=NOW)
    await assign_new_account(db_session, b.id, now=NOW)
    v2 = await _publish_v2(db_session, v1)
    rollout = await create_rollout(
        db_session, v2.id, audience="all_accounts", effective_at=NOW + timedelta(days=1)
    )
    at = NOW + timedelta(days=2)
    first = await execute_rollout(db_session, rollout.id, now=at)
    assert first.accounts_applied == 2
    # Simulate a crash-and-retry: force status back and run again.
    rollout.status = "running"
    await db_session.flush()
    second = await execute_rollout(db_session, rollout.id, now=at + timedelta(hours=1))
    assert second.status == "completed" and second.accounts_applied == 2
    rows = (await db_session.execute(
        select(CommercialPricingAssignment).where(
            CommercialPricingAssignment.audit_ref == f"rollout:{rollout.id}"
        )
    )).scalars().all()
    assert len(rows) == 2  # one per account, never duplicated


async def test_account_created_during_rollout_gets_one_assignment(db_session):
    """An account created after effective_at already got the target version via
    the updated new-account default — the rollout must not stack a second."""
    v1 = await seed_commercial_v1(db_session)
    v2 = await _publish_v2(db_session, v1)
    rollout = await create_rollout(
        db_session, v2.id, audience="all_accounts", effective_at=NOW + timedelta(days=1)
    )
    late = await _mk_account(db_session, "late")
    # Signs up between effective_at and execution: default is already v2.
    await assign_new_account(db_session, late.id, now=NOW + timedelta(days=1, hours=1))
    at = NOW + timedelta(days=1, hours=2)
    done = await execute_rollout(db_session, rollout.id, now=at)
    assert done.status == "completed"
    rows = (await db_session.execute(
        select(CommercialPricingAssignment).where(
            CommercialPricingAssignment.account_id == late.id
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "new_account_default"


async def test_manual_future_assignment_survives_rollout(db_session):
    """A pre-existing later assignment is surfaced as a failure, never clobbered."""
    v1 = await seed_commercial_v1(db_session)
    account = await _mk_account(db_session, "pinned")
    await assign_new_account(db_session, account.id, now=NOW)  # starts on v1
    v2 = await _publish_v2(db_session, v1)
    far_future = NOW + timedelta(days=365)
    manual = await assign_version(
        db_session, account.id, v1.id, effective_at=far_future, source="manual_test"
    )
    rollout = await create_rollout(
        db_session, v2.id, audience="selected_accounts",
        effective_at=NOW + timedelta(days=1), selected_account_ids=[account.id],
    )
    done = await execute_rollout(db_session, rollout.id, now=NOW + timedelta(days=2))
    assert done.status == "completed_with_failures"
    assert done.accounts_failed == 1
    still = await db_session.get(CommercialPricingAssignment, manual.id)
    assert still.ends_at is None  # manual plan untouched


async def test_rollout_runs_through_outbox_worker(db_session):
    """End-to-end: the enqueued job executes the rollout via the worker."""
    v1 = await seed_commercial_v1(db_session)
    account = await _mk_account(db_session, "acme")
    await assign_new_account(db_session, account.id, now=NOW)
    v2 = await _publish_v2(db_session, v1)
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    rollout = await create_rollout(
        db_session, v2.id, audience="selected_accounts",
        effective_at=past, selected_account_ids=[account.id],
    )
    await db_session.commit()
    done = await run_once(db_session, worker_id="test-worker")
    assert done == 1
    await db_session.refresh(rollout)
    assert rollout.status == "completed"
    job = (await db_session.execute(
        select(BillingJob).where(BillingJob.dedupe_key == f"pricing_rollout:{rollout.id}")
    )).scalar_one()
    assert job.status == "succeeded"
    assert job.result["applied"] == 1


# ── Account-creation hook (auth_routes) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_signup_assigns_pricing_in_same_transaction(db_session, _patch_db):
    from cloud.api.auth_routes import _upsert_user_and_account
    from cloud.auth.identity import UserInfo

    v1 = await seed_commercial_v1(db_session)
    await db_session.commit()
    info = UserInfo(sub="new-sub", email="new@example.com", name="New", avatar_url=None)
    user, account = await _upsert_user_and_account(info)
    assignment = (await db_session.execute(
        select(CommercialPricingAssignment).where(
            CommercialPricingAssignment.account_id == account.id
        )
    )).scalar_one()
    assert assignment.commercial_pricing_version_id == v1.id
    assert assignment.source == "new_account_default"
    billing = (await db_session.execute(
        select(BillingAccount).where(BillingAccount.account_id == account.id)
    )).scalar_one()
    assert billing.current_assignment_id == assignment.id
    # Second login of the same user creates nothing new.
    await _upsert_user_and_account(info)
    rows = (await db_session.execute(
        select(CommercialPricingAssignment).where(
            CommercialPricingAssignment.account_id == account.id
        )
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_signup_survives_unseeded_billing(db_session, _patch_db):
    """No published version yet → account still created, no assignment."""
    from cloud.api.auth_routes import _upsert_user_and_account
    from cloud.auth.identity import UserInfo

    info = UserInfo(sub="lone-sub", email="lone@example.com", name="Lone", avatar_url=None)
    user, account = await _upsert_user_and_account(info)
    assert account.id is not None
    rows = (await db_session.execute(
        select(CommercialPricingAssignment).where(
            CommercialPricingAssignment.account_id == account.id
        )
    )).scalars().all()
    assert rows == []
