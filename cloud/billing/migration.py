"""Existing-account migration onto billing v1 (039/010, review M9).

Two halves, both idempotent:

    plan_migration()    — the dry run. Reconciles actual runtime state and
                          produces a signed manifest: per-account decisions
                          (which Luna stays running, which are stopped, gift
                          and hosting amounts) plus totals and a content
                          hash. No writes.
    execute_migration() — takes exactly that manifest. Before ANY mutation it
                          re-plans the not-yet-migrated accounts and compares
                          them field-for-field against the manifest; a single
                          mismatch (state moved since the dry run) aborts
                          with zero writes. Already-migrated accounts replay:
                          their prior grant/period are returned, nothing new
                          is posted.

Per migrated account (owner decision — trial treatment):
    - one `migration` gift, source key ``migration:{account_id}:v1``,
      amounts from the assigned version's ``config.migration_gift``;
    - the most recently active RUNNING Luna stays up: it is charged one
      hosting month and gets its first hosting period opened at migration
      time (anchor = migration day) — the renewal sweep only renews, it
      never opens first periods;
    - every other running Luna gets a durable stop job (machine stopped,
      nothing deleted — data retention per plan 039/010);
    - stopped/error Lunas get no hosting period;
    - per-Luna trial limits are applied insert-only to the kept Luna.

Accounts created at/after ``cutover_at`` are excluded — they get the normal
new-account treatment. Financial history is never rewritten: reruns return
prior results, corrections are append-only.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing import assignments as assignments_svc
from cloud.billing import ledger, rating
from cloud.billing.grants import apply_trial_agent_limits
from cloud.billing.hosting import SUSPEND_JOB, add_month_clamped, hosting_price
from cloud.billing.models import AgentHostingPeriod, CreditGrant
from cloud.billing.worker import enqueue
from cloud.db.models import Agent, AuditLog

ALGORITHM = "migration_v1"

# Stable idempotency keys — v1 suffix so a future corrective pass can use v2
# without colliding with history.
def gift_source_key(account_id: uuid.UUID) -> str:
    return f"migration:{account_id}:v1"


def hosting_charge_key(agent_id: uuid.UUID) -> str:
    return f"migration:hosting:{agent_id}:v1"


def stop_dedupe_key(agent_id: uuid.UUID) -> str:
    return f"migration:stop:{agent_id}:v1"


class MigrationMismatch(RuntimeError):
    """Live state no longer matches the manifest — nothing was written."""

    def __init__(self, mismatches: list[dict]):
        self.mismatches = mismatches
        super().__init__(
            f"{len(mismatches)} account(s) diverged from the manifest; aborted with no writes"
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """Normalize for comparison — SQLite round-trips timestamptz as naive."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def manifest_hash(per_account: list[dict], totals: dict) -> str:
    payload = json.dumps(
        {"algorithm": ALGORITHM, "per_account": per_account, "totals": totals},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _entry_key(entry: dict) -> tuple:
    """The fields that must not drift between dry run and execution."""
    return (
        entry["account_id"],
        entry["keep_agent_id"],
        tuple(sorted(entry["stop_agent_ids"])),
        entry["gift_credits"],
        entry["gift_days"],
        entry["hosting_charge_credits"],
    )


async def _account_entry(
    session: AsyncSession, account, now: datetime
) -> dict:
    agents = (
        await session.execute(
            select(Agent)
            .where(Agent.account_id == account.id, Agent.deleted_at.is_(None))
            .order_by(Agent.created_at)
        )
    ).scalars().all()
    running = [a for a in agents if a.status == "running"]
    # Most recently active stays up; fall back to creation time so a fresh
    # never-used running Luna still wins over an older idle one.
    keep = max(
        running,
        key=lambda a: (_aware(a.last_active_at or a.created_at), _aware(a.created_at)),
        default=None,
    )
    stops = [a for a in running if keep is not None and a.id != keep.id]

    _, config = await rating.resolve_commercial_version(session, account.id, now)
    gift_cfg = config.get("migration_gift") or {}
    gift_credits = int(gift_cfg.get("credits") or 0)
    gift_days = int(gift_cfg.get("days") or 28)
    price = hosting_price(config) if keep is not None else 0

    existing_grant = (
        await session.execute(
            select(CreditGrant).where(CreditGrant.source_key == gift_source_key(account.id))
        )
    ).scalar_one_or_none()
    assignment = await assignments_svc.assignment_for_account_at(session, account.id, now)

    return {
        "account_id": str(account.id),
        "slug": account.slug,
        "agents_total": len(agents),
        "agents_running": len(running),
        "agents_not_running": len(agents) - len(running),
        "keep_agent_id": str(keep.id) if keep is not None else None,
        "stop_agent_ids": sorted(str(a.id) for a in stops),
        "gift_credits": gift_credits,
        "gift_days": gift_days,
        "hosting_charge_credits": price,
        "has_assignment": assignment is not None,
        "already_migrated": existing_grant is not None,
    }


async def plan_migration(
    session: AsyncSession,
    *,
    cutover_at: datetime,
    account_ids: list[uuid.UUID] | None = None,
    now: datetime | None = None,
) -> dict:
    """Dry run — reconcile live state into a signed manifest. Read-only."""
    from cloud.db.models import Account

    now = now or _utcnow()
    query = select(Account).where(Account.created_at < cutover_at).order_by(Account.id)
    if account_ids:
        query = query.where(Account.id.in_(account_ids))
    accounts = (await session.execute(query)).scalars().all()

    per_account = [await _account_entry(session, account, now) for account in accounts]
    pending = [e for e in per_account if not e["already_migrated"]]
    totals = {
        "accounts": len(per_account),
        "already_migrated": len(per_account) - len(pending),
        "pending": len(pending),
        "running_lunas": sum(e["agents_running"] for e in per_account),
        "not_running_lunas": sum(e["agents_not_running"] for e in per_account),
        "keeps": sum(1 for e in pending if e["keep_agent_id"]),
        "stops": sum(len(e["stop_agent_ids"]) for e in pending),
        "gift_credits_total": sum(e["gift_credits"] for e in pending),
        "hosting_charges_total": sum(
            e["hosting_charge_credits"] for e in pending if e["keep_agent_id"]
        ),
        "accounts_without_assignment": sum(1 for e in per_account if not e["has_assignment"]),
    }
    totals["resulting_liability_credits"] = (
        totals["gift_credits_total"] - totals["hosting_charges_total"]
    )
    return {
        "algorithm": ALGORITHM,
        "generated_at": now.isoformat(),
        "cutover_at": cutover_at.isoformat(),
        "account_ids": sorted(str(a) for a in account_ids) if account_ids else None,
        "per_account": per_account,
        "totals": totals,
        "content_hash": manifest_hash(per_account, totals),
    }


async def _migrate_account(
    session: AsyncSession, entry: dict, *, actor: str, now: datetime
) -> dict:
    account_id = uuid.UUID(entry["account_id"])
    await ledger.lock_billing_account(session, account_id)

    grant = None
    if entry["gift_credits"] > 0:
        grant = await ledger.create_grant(
            session,
            account_id=account_id,
            source_type="gift",
            source_key=gift_source_key(account_id),
            credits=entry["gift_credits"],
            visible_category="gift",
            effective_at=now,
            expires_at=now + timedelta(days=entry["gift_days"]),
            actor=actor,
            reason="billing v1 migration gift",
            now=now,
        )

    period_id = None
    charge_txn_id = None
    if entry["keep_agent_id"]:
        keep_id = uuid.UUID(entry["keep_agent_id"])
        version_id, config = await rating.resolve_commercial_version(session, account_id, now)
        await apply_trial_agent_limits(session, keep_id, config)
        open_period = (
            await session.execute(
                select(AgentHostingPeriod).where(
                    AgentHostingPeriod.agent_id == keep_id,
                    AgentHostingPeriod.state.in_(["pending", "active", "payment_due"]),
                )
            )
        ).scalars().first()
        if open_period is not None:
            period_id = open_period.id  # replay — never a second first-period
        else:
            period = AgentHostingPeriod(
                agent_id=keep_id,
                account_id=account_id,
                starts_at=now,
                ends_at=add_month_clamped(now.day, now),
                price_credits=entry["hosting_charge_credits"],
                commercial_pricing_version_id=version_id,
                state="active",
            )
            session.add(period)
            await session.flush()
            txn = await ledger.charge(
                session,
                account_id=account_id,
                idempotency_key=hosting_charge_key(keep_id),
                credits=entry["hosting_charge_credits"],
                agent_id=keep_id,
                service="hosting",
                source_ref=str(period.id),
                commercial_pricing_version_id=version_id,
                reason="billing v1 migration — first hosting month",
                actor=actor,
                now=now,
            )
            period.charge_transaction_id = txn.id
            period_id = period.id
            charge_txn_id = txn.id

    for agent_id in entry["stop_agent_ids"]:
        await enqueue(
            session,
            job_type=SUSPEND_JOB,
            payload={"agent_id": agent_id},
            dedupe_key=stop_dedupe_key(uuid.UUID(agent_id)),
        )

    session.add(AuditLog(
        account_id=account_id,
        action="billing.migration.account",
        target=f"account:{account_id}",
        metadata_={"actor": actor, "algorithm": ALGORITHM},
        after_state=entry,
    ))
    await session.flush()
    return {
        "account_id": entry["account_id"],
        "grant_id": str(grant.id) if grant else None,
        "hosting_period_id": str(period_id) if period_id else None,
        "hosting_charge_transaction_id": str(charge_txn_id) if charge_txn_id else None,
        "stop_jobs": len(entry["stop_agent_ids"]),
    }


async def execute_migration(
    session: AsyncSession,
    *,
    manifest: dict,
    actor: str,
    now: datetime | None = None,
) -> dict:
    """Apply a dry-run manifest. Verifies live state still matches it before
    the first write; commits once at the end (caller's session/transaction).
    Rerun-safe: already-migrated accounts replay their prior results."""
    now = now or _utcnow()
    if manifest.get("algorithm") != ALGORITHM:
        raise MigrationMismatch([{"error": f"unknown algorithm {manifest.get('algorithm')!r}"}])
    if manifest_hash(manifest["per_account"], manifest["totals"]) != manifest.get("content_hash"):
        raise MigrationMismatch([{"error": "manifest content_hash does not match its contents"}])

    replayed: list[dict] = []
    to_apply: list[dict] = []
    mismatches: list[dict] = []
    from cloud.db.models import Account

    for entry in manifest["per_account"]:
        account_id = uuid.UUID(entry["account_id"])
        existing = (
            await session.execute(
                select(CreditGrant).where(
                    CreditGrant.source_key == gift_source_key(account_id)
                )
            )
        ).scalar_one_or_none()
        if existing is not None or entry["already_migrated"]:
            replayed.append({"account_id": entry["account_id"],
                             "grant_id": str(existing.id) if existing else None})
            continue
        account = await session.get(Account, account_id)
        if account is None:
            mismatches.append({"account_id": entry["account_id"], "error": "account gone"})
            continue
        current = await _account_entry(session, account, now)
        if _entry_key(current) != _entry_key(entry):
            mismatches.append({
                "account_id": entry["account_id"],
                "manifest": entry,
                "current": current,
            })
            continue
        to_apply.append(entry)

    if mismatches:
        raise MigrationMismatch(mismatches)

    results = [await _migrate_account(session, e, actor=actor, now=now) for e in to_apply]
    await session.commit()
    return {
        "algorithm": ALGORITHM,
        "executed_at": now.isoformat(),
        "manifest_hash": manifest["content_hash"],
        "applied": results,
        "replayed": replayed,
        "totals": {
            "applied": len(results),
            "replayed": len(replayed),
            "gift_credits_posted": sum(
                e["gift_credits"] for e in to_apply
            ),
            "hosting_charges_posted": sum(
                e["hosting_charge_credits"] for e in to_apply if e["keep_agent_id"]
            ),
            "stop_jobs_enqueued": sum(len(e["stop_agent_ids"]) for e in to_apply),
        },
    }
