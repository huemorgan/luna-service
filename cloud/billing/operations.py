"""Billing operations (039/009): counters, invariants, alerts, heartbeats.

Everything here is read-mostly and bounded — the ops snapshot must stay
cheap enough to render on every admin page load. The only writes are
`ops_alerts` upserts and `ops_heartbeats` stamps.

Alert philosophy: bounded debt is expected behavior (charges post in full,
even into debt), so there is deliberately no raw negative-balance alert —
drift, dead money-moving jobs and broken invariants are the real signals.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing.models import (
    AccountBalanceProjection,
    AgentHostingPeriod,
    BillableEvent,
    BillingHold,
    BillingJob,
    CommercialPricingVersion,
    CreditConsumption,
    CreditGrant,
    CreditLedgerPosting,
    CreditLedgerTransaction,
    OpsAlert,
    OpsHeartbeat,
    ProcessedWebhook,
    RatedCharge,
    StripePayment,
    StripePriceBinding,
)
from cloud.billing.ledger import DEBT, WALLET
from cloud.billing.stripe_clawback import clawback_target_credits

log = logging.getLogger("billing.operations")

WOULD_BLOCK_WINDOW = timedelta(days=7)
UNRATED_SCAN_LIMIT = 5_000
WEBHOOK_STALE_AFTER = timedelta(minutes=5)
HOSTING_PENDING_STUCK_AFTER = timedelta(hours=1)
SCHEDULED_LOT_BACKLOG_AFTER = timedelta(minutes=15)
NEGATIVE_MARGIN_WINDOW = timedelta(days=7)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── Heartbeats ───────────────────────────────────────────────────────────────

async def heartbeat(session: AsyncSession, name: str, detail: dict | None = None) -> None:
    row = await session.get(OpsHeartbeat, name)
    if row is None:
        session.add(OpsHeartbeat(name=name, last_run_at=_utcnow(), detail=detail))
    else:
        row.last_run_at = _utcnow()
        row.detail = detail
    await session.flush()


async def heartbeats(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(select(OpsHeartbeat))).scalars().all()
    return [
        {"name": r.name, "last_run_at": _aware(r.last_run_at).isoformat(), "detail": r.detail}
        for r in sorted(rows, key=lambda r: r.name)
    ]


# ── Invariants ───────────────────────────────────────────────────────────────

async def check_trial_balance(session: AsyncSession, *, limit: int = 20) -> dict:
    """Double-entry journal invariant: every transaction's postings sum to
    zero, so the global sum is zero. Returns the offending transactions."""
    total = (
        await session.execute(select(func.coalesce(func.sum(CreditLedgerPosting.credits), 0)))
    ).scalar_one()
    unbalanced = (
        await session.execute(
            select(CreditLedgerPosting.transaction_id, func.sum(CreditLedgerPosting.credits))
            .group_by(CreditLedgerPosting.transaction_id)
            .having(func.sum(CreditLedgerPosting.credits) != 0)
            .limit(limit)
        )
    ).all()
    return {
        "total": int(total),
        "unbalanced_transactions": [
            {"transaction_id": str(t), "sum": int(s)} for t, s in unbalanced
        ],
        "ok": int(total) == 0 and not unbalanced,
    }


async def check_projection_drift(session: AsyncSession, *, limit: int = 20) -> dict:
    """Posted balance and debt in the read model vs a full ledger replay."""
    posted = dict(
        (
            await session.execute(
                select(CreditLedgerPosting.account_id, func.sum(CreditLedgerPosting.credits))
                .where(CreditLedgerPosting.ledger_account == WALLET)
                .group_by(CreditLedgerPosting.account_id)
            )
        ).all()
    )
    debt = dict(
        (
            await session.execute(
                select(CreditLedgerPosting.account_id, func.sum(CreditLedgerPosting.credits))
                .where(CreditLedgerPosting.ledger_account == DEBT)
                .group_by(CreditLedgerPosting.account_id)
            )
        ).all()
    )
    projections = (await session.execute(select(AccountBalanceProjection))).scalars().all()
    drifted = []
    for projection in projections:
        expected_posted = int(posted.get(projection.account_id, 0))
        expected_debt = int(debt.get(projection.account_id, 0))
        if (
            projection.posted_balance_credits != expected_posted
            or projection.debt_credits != expected_debt
        ):
            drifted.append({
                "account_id": str(projection.account_id),
                "projected_balance": projection.posted_balance_credits,
                "ledger_balance": expected_posted,
                "projected_debt": projection.debt_credits,
                "ledger_debt": expected_debt,
            })
    # Accounts with postings but no projection row are drift too.
    missing = [
        str(account_id) for account_id in posted
        if account_id not in {p.account_id for p in projections}
    ]
    return {
        "drifted": drifted[:limit],
        "drifted_count": len(drifted),
        "missing_projection": missing[:limit],
        "ok": not drifted and not missing,
    }


async def check_grant_remainders(session: AsyncSession, *, limit: int = 20) -> dict:
    """For live lots: remaining == original − effective consumption, where a
    consumption is effective unless its charge transaction was reversed."""
    reversed_ids = select(CreditLedgerTransaction.reversal_of_id).where(
        CreditLedgerTransaction.reversal_of_id.is_not(None)
    )
    consumed = dict(
        (
            await session.execute(
                select(CreditConsumption.grant_id, func.sum(CreditConsumption.credits))
                .where(
                    CreditConsumption.grant_id.is_not(None),
                    CreditConsumption.charge_transaction_id.not_in(reversed_ids),
                )
                .group_by(CreditConsumption.grant_id)
            )
        ).all()
    )
    grants = (
        await session.execute(
            select(CreditGrant).where(CreditGrant.status.in_(["active", "exhausted"]))
        )
    ).scalars().all()
    drifted = []
    for grant in grants:
        expected = grant.original_credits - int(consumed.get(grant.id, 0))
        if grant.remaining_credits != expected:
            drifted.append({
                "grant_id": str(grant.id),
                "source_key": grant.source_key,
                "remaining": grant.remaining_credits,
                "expected": expected,
            })
    return {"drifted": drifted[:limit], "drifted_count": len(drifted), "ok": not drifted}


async def run_invariants(session: AsyncSession) -> dict:
    return {
        "trial_balance": await check_trial_balance(session),
        "projection_drift": await check_projection_drift(session),
        "grant_remainders": await check_grant_remainders(session),
    }


# ── Counters ─────────────────────────────────────────────────────────────────

async def _hold_counters(session: AsyncSession) -> dict:
    rows = (
        await session.execute(
            select(
                BillingHold.status,
                func.count(BillingHold.id),
                func.coalesce(func.sum(BillingHold.estimated_credits), 0),
            ).group_by(BillingHold.status)
        )
    ).all()
    by_status = {status: {"count": int(c), "credits": int(s)} for status, c, s in rows}
    return {
        "open": by_status.get("open", {"count": 0, "credits": 0}),
        "needs_reconciliation": by_status.get("needs_reconciliation", {"count": 0, "credits": 0}),
    }


async def _charge_counters(session: AsyncSession) -> dict:
    rows = (
        await session.execute(
            select(RatedCharge.charge_status, func.count(RatedCharge.id))
            .group_by(RatedCharge.charge_status)
        )
    ).all()
    return {status: int(c) for status, c in rows}


async def _would_block_counters(session: AsyncSession, now: datetime) -> dict:
    """Shadow-mode would_block frequency by code — the go/no-go signal for
    the 010 enforce flip. Python-side aggregation: the code lives inside
    quantity_json and the window is bounded."""
    rows = (
        await session.execute(
            select(BillableEvent.quantity_json)
            .where(
                BillableEvent.status == "would_block",
                BillableEvent.event_at >= now - WOULD_BLOCK_WINDOW,
            )
            .limit(UNRATED_SCAN_LIMIT)
        )
    ).scalars().all()
    by_code: dict[str, int] = {}
    for quantity in rows:
        code = (quantity or {}).get("would_block") or "unknown"
        by_code[code] = by_code.get(code, 0) + 1
    return {"window_days": WOULD_BLOCK_WINDOW.days, "by_code": by_code, "total": len(rows)}


async def _unrated_dimension_gaps(session: AsyncSession, now: datetime) -> list[str]:
    """Distinct provider:model:dimension gaps recorded by rating — the
    worklist for completing the provider cost table."""
    rows = (
        await session.execute(
            select(RatedCharge.rule_snapshot)
            .where(RatedCharge.created_at >= now - WOULD_BLOCK_WINDOW)
            .order_by(RatedCharge.created_at.desc())
            .limit(UNRATED_SCAN_LIMIT)
        )
    ).scalars().all()
    gaps: set[str] = set()
    for snapshot in rows:
        for gap in (snapshot or {}).get("unrated_dimensions") or []:
            gaps.add(gap)
    return sorted(gaps)


async def _worker_counters(session: AsyncSession, now: datetime) -> dict:
    rows = (
        await session.execute(
            select(BillingJob.job_type, BillingJob.status, func.count(BillingJob.id))
            .group_by(BillingJob.job_type, BillingJob.status)
        )
    ).all()
    by_type: dict[str, dict[str, int]] = {}
    for job_type, status, count in rows:
        by_type.setdefault(job_type, {})[status] = int(count)
    oldest_pending = (
        await session.execute(
            select(func.min(BillingJob.next_attempt_at)).where(BillingJob.status == "pending")
        )
    ).scalar_one()
    dead = [
        {"job_type": job_type, "count": statuses["dead"]}
        for job_type, statuses in sorted(by_type.items())
        if statuses.get("dead")
    ]
    oldest_age = None
    if oldest_pending is not None:
        oldest_age = max(0, int((now - _aware(oldest_pending)).total_seconds()))
    return {
        "by_type": by_type,
        "dead": dead,
        "dead_money_jobs": sum(d["count"] for d in dead if d["job_type"].startswith("stripe")),
        "oldest_pending_age_seconds": oldest_age,
    }


async def _webhook_counters(session: AsyncSession, now: datetime) -> dict:
    errors = (
        await session.execute(
            select(func.count(ProcessedWebhook.id)).where(ProcessedWebhook.state == "error")
        )
    ).scalar_one()
    stale_queued = (
        await session.execute(
            select(func.count(ProcessedWebhook.id)).where(
                ProcessedWebhook.state == "queued",
                ProcessedWebhook.created_at < now - WEBHOOK_STALE_AFTER,
            )
        )
    ).scalar_one()
    return {"error": int(errors), "stale_queued": int(stale_queued)}


async def _hosting_counters(session: AsyncSession, now: datetime) -> dict:
    stuck_pending = (
        await session.execute(
            select(func.count(AgentHostingPeriod.id)).where(
                AgentHostingPeriod.state == "pending",
                AgentHostingPeriod.created_at < now - HOSTING_PENDING_STUCK_AFTER,
            )
        )
    ).scalar_one()
    payment_due = (
        await session.execute(
            select(func.count(AgentHostingPeriod.id)).where(
                AgentHostingPeriod.state == "payment_due"
            )
        )
    ).scalar_one()
    # The settle-failed/hold-missing path activates without a charge; those
    # periods must be reconciled by hand and never disappear silently.
    uncharged_active = (
        await session.execute(
            select(func.count(AgentHostingPeriod.id)).where(
                AgentHostingPeriod.state.in_(["active", "paid"]),
                AgentHostingPeriod.charge_transaction_id.is_(None),
            )
        )
    ).scalar_one()
    return {
        "stuck_pending": int(stuck_pending),
        "payment_due": int(payment_due),
        "active_without_charge": int(uncharged_active),
    }


async def _scheduled_lot_counters(session: AsyncSession, now: datetime) -> dict:
    backlog = (
        await session.execute(
            select(func.count(CreditGrant.id)).where(
                CreditGrant.status == "scheduled",
                CreditGrant.effective_at < now - SCHEDULED_LOT_BACKLOG_AFTER,
            )
        )
    ).scalar_one()
    return {"activation_backlog": int(backlog)}


async def _clawback_drift(session: AsyncSession, *, limit: int = 20) -> dict:
    """Payments whose clawed_credits disagree with the target implied by
    their own refund/dispute accumulators (a dead clawback job, usually)."""
    payments = (
        await session.execute(
            select(StripePayment).where(
                (StripePayment.refunded_pretax_cents > 0)
                | (StripePayment.disputed_pretax_cents > 0)
            )
        )
    ).scalars().all()
    drifted = []
    for payment in payments:
        target = clawback_target_credits(payment)
        if payment.clawed_credits != target:
            drifted.append({
                "payment_ref": payment.payment_ref,
                "clawed_credits": payment.clawed_credits,
                "target_credits": target,
            })
    return {"drifted": drifted[:limit], "drifted_count": len(drifted)}


async def _unbound_product_keys(session: AsyncSession) -> dict:
    """Which catalog product keys have no Stripe binding, per mode — the
    payments_enabled derivation made visible."""
    version = (
        await session.execute(
            select(CommercialPricingVersion)
            .where(CommercialPricingVersion.status == "published")
            .order_by(CommercialPricingVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if version is None:
        return {"test": [], "live": [], "no_published_version": True}
    keys = sorted(p["key"] for p in version.config_json.get("products") or [])
    bindings = (await session.execute(select(StripePriceBinding))).scalars().all()
    bound = {(b.livemode, b.product_key) for b in bindings}
    return {
        "test": [k for k in keys if (False, k) not in bound],
        "live": [k for k in keys if (True, k) not in bound],
    }


async def _negative_margin_calls(session: AsyncSession, now: datetime) -> int:
    """Settled/observed calls whose face value did not cover vendor cost —
    a mispriced SKU/context if it recurs."""
    count = (
        await session.execute(
            select(func.count(RatedCharge.id)).where(
                RatedCharge.created_at >= now - NEGATIVE_MARGIN_WINDOW,
                RatedCharge.credits * 10_000
                < RatedCharge.vendor_cost_micro_usd + RatedCharge.luna_absorbed_micro_usd,
            )
        )
    ).scalar_one()
    return int(count)


async def ops_snapshot(session: AsyncSession, *, now: datetime | None = None) -> dict:
    now = now or _utcnow()
    return {
        "generated_at": now.isoformat(),
        "holds": await _hold_counters(session),
        "rated_charges": await _charge_counters(session),
        "would_block": await _would_block_counters(session, now),
        "unrated_dimensions": await _unrated_dimension_gaps(session, now),
        "worker": await _worker_counters(session, now),
        "webhooks": await _webhook_counters(session, now),
        "hosting": await _hosting_counters(session, now),
        "scheduled_lots": await _scheduled_lot_counters(session, now),
        "clawback": await _clawback_drift(session),
        "stripe_bindings": await _unbound_product_keys(session),
        "negative_margin_calls_7d": await _negative_margin_calls(session, now),
        "heartbeats": await heartbeats(session),
    }


# ── Alerts ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AlertRule:
    key: str
    severity: str
    dedupe_window: timedelta
    message: str


ALERT_RULES = {
    "trial_balance": AlertRule("trial_balance", "critical", timedelta(hours=1),
                               "ledger journal does not balance"),
    "projection_drift": AlertRule("projection_drift", "critical", timedelta(hours=1),
                                  "balance projection disagrees with ledger replay"),
    "grant_remainder_drift": AlertRule("grant_remainder_drift", "critical", timedelta(hours=1),
                                       "grant remainders disagree with consumption history"),
    "dead_money_jobs": AlertRule("dead_money_jobs", "critical", timedelta(minutes=30),
                                 "dead stripe.* outbox jobs — money moved with no local effect"),
    "dead_jobs": AlertRule("dead_jobs", "warning", timedelta(hours=1),
                           "dead billing outbox jobs"),
    "webhook_errors": AlertRule("webhook_errors", "warning", timedelta(hours=1),
                                "stripe webhooks in error state or stale in queue"),
    "holds_needs_reconciliation": AlertRule("holds_needs_reconciliation", "warning", timedelta(hours=4),
                                            "stale holds awaiting operator reconciliation"),
    "hosting_stuck": AlertRule("hosting_stuck", "warning", timedelta(hours=1),
                               "hosting periods stuck pending or active without a charge"),
    "scheduled_lot_backlog": AlertRule("scheduled_lot_backlog", "warning", timedelta(hours=1),
                                       "scheduled grant lots past their activation boundary"),
    "clawback_drift": AlertRule("clawback_drift", "critical", timedelta(hours=1),
                                "stripe payment clawbacks off their refund/dispute target"),
    "negative_margin": AlertRule("negative_margin", "warning", timedelta(hours=12),
                                 "calls rated below vendor cost in the last 7 days"),
}

# Thresholds: a signal at or below its threshold is healthy. Bounded debt and
# dunning are expected states, so payment_due deliberately has no alert.
ALERT_THRESHOLDS = {
    "trial_balance": 0,
    "projection_drift": 0,
    "grant_remainder_drift": 0,
    "dead_money_jobs": 0,
    "dead_jobs": 0,
    "webhook_errors": 0,
    "holds_needs_reconciliation": 0,
    "hosting_stuck": 0,
    "scheduled_lot_backlog": 0,
    "clawback_drift": 0,
    "negative_margin": 0,
}


def _signals(snapshot: dict, invariants: dict) -> dict[str, int]:
    worker = snapshot["worker"]
    webhooks = snapshot["webhooks"]
    hosting = snapshot["hosting"]
    return {
        "trial_balance": 0 if invariants["trial_balance"]["ok"] else 1,
        "projection_drift": invariants["projection_drift"]["drifted_count"]
        + len(invariants["projection_drift"]["missing_projection"]),
        "grant_remainder_drift": invariants["grant_remainders"]["drifted_count"],
        "dead_money_jobs": worker["dead_money_jobs"],
        "dead_jobs": sum(d["count"] for d in worker["dead"]) - worker["dead_money_jobs"],
        "webhook_errors": webhooks["error"] + webhooks["stale_queued"],
        "holds_needs_reconciliation": snapshot["holds"]["needs_reconciliation"]["count"],
        "hosting_stuck": hosting["stuck_pending"] + hosting["active_without_charge"],
        "scheduled_lot_backlog": snapshot["scheduled_lots"]["activation_backlog"],
        "clawback_drift": snapshot["clawback"]["drifted_count"],
        "negative_margin": snapshot["negative_margin_calls_7d"],
    }


ALERT_EVAL_INTERVAL_SECONDS = 300.0


async def ops_loop(session_factory, *, interval_seconds: float = ALERT_EVAL_INTERVAL_SECONDS) -> None:
    """Periodic alert evaluation. Runs beside the outbox worker and the
    maintenance loop under the billing advisory lock (wired in cloud/main.py)."""
    import asyncio

    while True:
        try:
            async with session_factory() as session:
                active = await evaluate_alerts(session)
                await session.commit()
                if active:
                    log.warning("billing ops alerts active: %s",
                                [a["alert_key"] for a in active])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("billing ops alert evaluation failed")
        await asyncio.sleep(interval_seconds)


async def evaluate_alerts(
    session: AsyncSession, *, now: datetime | None = None,
    snapshot: dict | None = None, invariants: dict | None = None,
) -> list[dict]:
    """Evaluate every alert rule and upsert ops_alerts. Returns the active
    alerts. Dedupe: a signal re-firing within its rule's window reactivates
    the existing row (same first_seen_at) instead of opening a new incident."""
    now = now or _utcnow()
    snapshot = snapshot or await ops_snapshot(session, now=now)
    invariants = invariants or await run_invariants(session)
    signals = _signals(snapshot, invariants)

    existing = {
        a.alert_key: a for a in (await session.execute(select(OpsAlert))).scalars().all()
    }
    active: list[dict] = []
    for key, rule in ALERT_RULES.items():
        value = signals[key]
        threshold = ALERT_THRESHOLDS[key]
        firing = value > threshold
        row = existing.get(key)
        if firing:
            if row is None:
                row = OpsAlert(
                    alert_key=key, severity=rule.severity, message=rule.message,
                    value_json={"value": value}, threshold_json={"threshold": threshold},
                    status="active", first_seen_at=now, last_seen_at=now,
                )
                session.add(row)
            else:
                if row.status == "resolved":
                    # Outside the dedupe window this is a fresh incident;
                    # inside it, the same incident continuing.
                    if _aware(row.resolved_at) and now - _aware(row.resolved_at) > rule.dedupe_window:
                        row.first_seen_at = now
                    row.status = "active"
                    row.resolved_at = None
                row.severity = rule.severity
                row.message = rule.message
                row.value_json = {"value": value}
                row.threshold_json = {"threshold": threshold}
                row.last_seen_at = now
        elif row is not None and row.status == "active":
            row.status = "resolved"
            row.resolved_at = now
    await session.flush()
    for key, rule in ALERT_RULES.items():
        row = existing.get(key)
        if (row is not None and row.status == "active") or (row is None and signals[key] > ALERT_THRESHOLDS[key]):
            active.append({
                "alert_key": key, "severity": rule.severity, "message": rule.message,
                "value": signals[key], "threshold": ALERT_THRESHOLDS[key],
            })
    await heartbeat(session, "alert_eval", {"active": len(active)})
    return active
