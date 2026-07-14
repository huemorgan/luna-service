"""Customer billing API (039/008): public pricing, balances, grants,
usage, statements, and per-Luna limits.

Customer surfaces expose CREDITS ONLY — never internal dollars, margins,
pricing contexts, or model tiers. The pricing config is filtered to the
marketing-safe product fields before it leaves the server.

Stripe checkout/portal endpoints are deliberately absent until 039/007;
`payments_enabled: false` in /api/billing/products tells the UI to render
purchase actions disabled.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from cloud.auth.deps import enforce_same_origin, require_active_account
from cloud.billing import assignments as assignments_svc
from cloud.billing import ledger
from cloud.billing.grants import account_config, is_trial_account
from cloud.billing.hosting import hosting_price
from cloud.billing.models import (
    AccountBalanceProjection,
    AgentCreditLimit,
    AgentHostingPeriod,
    AgentLimitPeriod,
    BillableEvent,
    CommercialPricingVersion,
    CreditGrant,
    CreditLedgerPosting,
    CreditLedgerTransaction,
    RatedCharge,
)
from cloud.billing.rating import RatingUnavailable
from cloud.db.models import Account, Agent, Membership, User
from cloud.db.session import get_session as get_db_session

log = logging.getLogger(__name__)

public_router = APIRouter(prefix="/api/public", tags=["public"])
router = APIRouter(prefix="/api/billing", tags=["billing"])

_utcnow = lambda: datetime.now(timezone.utc)  # noqa: E731


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite (tests) returns naive datetimes; Postgres returns aware. All
    stored values are UTC, so pin the tzinfo before doing arithmetic."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── Marketing-safe config projection ─────────────────────────────────────────

def _public_product(p: dict) -> dict:
    """Only the fields a buyer may see. Everything else in the config
    (margins, tiers, SKU formulas) is internal and must never leak."""
    return {
        "key": p["key"],
        "kind": p["kind"],
        "interval": p.get("interval"),
        "price_usd_cents": p["price_usd_cents"],
        "paid_credits": p["paid_credits"],
        "bonus_credits": p.get("bonus_credits", 0),
        "yearly_gift_credits": p.get("yearly_gift_credits", 0),
        "monthly_paid_lot_credits": p.get("monthly_paid_lot_credits"),
        "monthly_bonus_lot_credits": p.get("monthly_bonus_lot_credits"),
    }


def _public_pricing(config: dict) -> dict:
    trial = config.get("trial") or {}
    return {
        "trial": {
            "gift_credits": trial.get("gift_credits"),
            "days": trial.get("days"),
            "daily_limit_credits": trial.get("daily_limit_credits"),
            "monthly_limit_credits": trial.get("monthly_limit_credits"),
            "active_luna_cap": trial.get("active_luna_cap"),
        },
        "hosting": {"price_credits": hosting_price(config), "period": "monthly"},
        "products": [_public_product(p) for p in config.get("products") or []],
        "topup_steps_usd_cents": config.get("topup_steps_usd_cents") or [],
        "credit_value_usd_cents": 1,  # 1 credit = $0.01, public by design
    }


@public_router.get("/pricing")
async def public_pricing():
    """The published new-account catalog — feeds the marketing pricing page."""
    async with get_db_session() as db:
        try:
            version_id = await assignments_svc.default_version_id(db)
        except Exception:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Pricing is not published yet"
            )
        version = await db.get(CommercialPricingVersion, version_id)
        return _public_pricing(version.config_json)


# ── Shared helpers ───────────────────────────────────────────────────────────

async def _require_owner(db, user: User, account: Account) -> None:
    """Fresh role check — sessions and caches must not grant owner powers."""
    role = (
        await db.execute(
            select(Membership.role).where(
                Membership.account_id == account.id,
                Membership.user_id == user.id,
                Membership.status == "active",
            )
        )
    ).scalar_one_or_none()
    if role != "owner":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the account owner can change billing settings"
        )


async def _account_agents(db, account_id: uuid.UUID, *, include_deleted: bool = False):
    q = select(Agent).where(Agent.account_id == account_id)
    if not include_deleted:
        q = q.where(Agent.deleted_at.is_(None))
    return (await db.execute(q.order_by(Agent.created_at.asc()))).scalars().all()


def _range_bounds(range_key: str, start: str | None, end: str | None) -> tuple[datetime, datetime]:
    now = _utcnow()
    if range_key == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    if range_key == "7d":
        return now - timedelta(days=7), now
    if range_key == "28d":
        return now - timedelta(days=28), now
    if range_key == "custom":
        try:
            s = datetime.fromisoformat(start).astimezone(timezone.utc)
            e = datetime.fromisoformat(end).astimezone(timezone.utc)
        except (TypeError, ValueError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "custom range needs valid ISO start/end")
        if e <= s or e - s > timedelta(days=366):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid custom range")
        return s, e
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "range must be today|7d|28d|custom")


ACTION_LABELS = {
    "chat": "Chat",
    "playbook_run": "Playbook run",
    "scheduled_run": "Scheduled run",
    "background_run": "Background run",
    "forge_job": "Forge job",
}


# ── Summary: balances, trial, hosting, recovery ──────────────────────────────

@router.get("/summary")
async def billing_summary(auth: tuple[User, Account] = Depends(require_active_account)):
    _, account = auth
    now = _utcnow()
    async with get_db_session() as db:
        await ledger.ensure_billing_account(db, account.id)
        proj = await ledger.rebuild_projection(db, account.id)
        trial = await is_trial_account(db, account.id)

        try:
            config = await account_config(db, account.id)
        except RatingUnavailable:
            config = {}
        host_price = hosting_price(config) if config else None

        trial_expires_at = None
        if trial:
            trial_expires_at = _aware(
                (
                    await db.execute(
                        select(CreditGrant.expires_at).where(
                            CreditGrant.account_id == account.id,
                            CreditGrant.source_key == f"trial:{account.id}",
                        )
                    )
                ).scalar_one_or_none()
            )

        agents = await _account_agents(db, account.id)
        periods = (
            await db.execute(
                select(AgentHostingPeriod)
                .where(
                    AgentHostingPeriod.account_id == account.id,
                    AgentHostingPeriod.state.in_(("pending", "active", "payment_due")),
                )
                .order_by(AgentHostingPeriod.starts_at.desc())
            )
        ).scalars().all()
        period_by_agent = {}
        for p in periods:
            period_by_agent.setdefault(p.agent_id, p)

        hosting = []
        payment_due_count = 0
        for a in agents:
            p = period_by_agent.get(a.id)
            if p and p.state == "payment_due":
                payment_due_count += 1
            hosting.append({
                "agent_id": str(a.id),
                "agent_name": a.name,
                "agent_status": a.status,
                "state": p.state if p else None,
                "period_starts_at": p.starts_at.isoformat() if p else None,
                "period_ends_at": p.ends_at.isoformat() if p else None,
                "price_credits": p.price_credits if p else None,
            })

        # Recovery math — the truthful "what do I need to pay" payload.
        debt = proj.debt_credits
        posted = proj.posted_balance_credits
        need_positive = max(0, -posted) + (1 if posted <= 0 else 0) if posted <= 0 else 0
        restart_credits = None
        if payment_due_count and host_price is not None:
            shortfall = payment_due_count * host_price - max(posted, 0)
            restart_credits = max(0, shortfall)

        await db.commit()  # persists the rebuilt projection read model
        return {
            "posted_balance_credits": posted,
            "open_exposure_credits": proj.open_exposure_credits,
            "debt_credits": debt,
            "balances": {
                "paid": proj.paid_credits,
                "bonus": proj.bonus_credits,
                "gift": proj.gift_credits,
                "free": proj.free_credits,
                "topup": proj.topup_credits,
            },
            "next_expiry_at": proj.next_expiry_at.isoformat() if proj.next_expiry_at else None,
            "trial": {
                "is_trial": trial,
                "expires_at": trial_expires_at.isoformat() if trial_expires_at else None,
                "days_remaining": max(0, (trial_expires_at - now).days) if trial_expires_at else None,
                "active_luna_cap": (config.get("trial") or {}).get("active_luna_cap") if trial else None,
            },
            "hosting": hosting,
            "hosting_price_credits": host_price,
            "recovery": {
                "debt_credits": debt,
                "credits_required_for_positive_balance": need_positive,
                "hosting_restart_credits": restart_credits,
                "payment_action_required": False,  # Stripe dunning lands in 007
                "next_payment_retry_at": None,
            },
            "payments_enabled": False,
        }


# ── Grants ───────────────────────────────────────────────────────────────────

@router.get("/grants")
async def list_grants(auth: tuple[User, Account] = Depends(require_active_account)):
    _, account = auth
    async with get_db_session() as db:
        grants = (
            await db.execute(
                select(CreditGrant)
                .where(CreditGrant.account_id == account.id)
                .order_by(CreditGrant.status.asc(), CreditGrant.burn_priority.asc(),
                          CreditGrant.effective_at.asc())
            )
        ).scalars().all()
        # "Use next" order: the burn order among active, unexpired grants.
        now = _utcnow()
        burn_order = 0
        out = []
        for g in grants:
            usable = (
                g.status == "active" and g.remaining_credits > 0
                and (g.expires_at is None or _aware(g.expires_at) > now)
            )
            if usable:
                burn_order += 1
            out.append({
                "id": str(g.id),
                "category": g.visible_category,
                "original_credits": g.original_credits,
                "remaining_credits": g.remaining_credits,
                "effective_at": g.effective_at.isoformat(),
                "expires_at": g.expires_at.isoformat() if g.expires_at else None,
                "status": g.status,
                "use_next_order": burn_order if usable else None,
            })
        return out


# ── Products (buyer's catalog; payments disabled until 007) ──────────────────

@router.get("/products")
async def my_products(auth: tuple[User, Account] = Depends(require_active_account)):
    _, account = auth
    async with get_db_session() as db:
        try:
            config = await account_config(db, account.id)
        except RatingUnavailable:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Pricing unavailable")
        return {**_public_pricing(config), "payments_enabled": False}


# ── Usage ────────────────────────────────────────────────────────────────────

BREAKDOWNS = {
    "agent": BillableEvent.agent_id,
    "service": BillableEvent.service,
    "plugin": BillableEvent.plugin,
    "action_type": BillableEvent.root_action_type,
    "model": BillableEvent.model,
    "root_action": BillableEvent.root_action_id,
}


@router.get("/usage/summary")
async def usage_summary(
    range: str = Query("28d"),
    start: str | None = None,
    end: str | None = None,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    since, until = _range_bounds(range, start, end)
    now = _utcnow()
    async with get_db_session() as db:
        total = (
            await db.execute(
                select(func.coalesce(func.sum(RatedCharge.credits), 0)).where(
                    RatedCharge.account_id == account.id,
                    RatedCharge.created_at >= since,
                    RatedCharge.created_at < until,
                )
            )
        ).scalar_one()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        today_used, month_used = [
            (
                await db.execute(
                    select(func.coalesce(func.sum(RatedCharge.credits), 0)).where(
                        RatedCharge.account_id == account.id,
                        RatedCharge.created_at >= s,
                    )
                )
            ).scalar_one()
            for s in (today_start, month_start)
        ]

        # Daily trend inside the range. func.date works on both Postgres and
        # the SQLite test harness (date_trunc is PG-only).
        day = func.date(RatedCharge.created_at)
        trend_rows = (
            await db.execute(
                select(day.label("day"), func.sum(RatedCharge.credits))
                .where(
                    RatedCharge.account_id == account.id,
                    RatedCharge.created_at >= since,
                    RatedCharge.created_at < until,
                )
                .group_by(day).order_by(day)
            )
        ).all()
        trend = [{"day": str(r[0])[:10], "credits": int(r[1])} for r in trend_rows]

        # Projection: average of the trend, clearly an estimate (UI labels it).
        proj = await ledger.rebuild_projection(db, account.id)
        avg = (sum(t["credits"] for t in trend) / max(len(trend), 1)) if trend else 0
        balance = int(proj.posted_balance_credits)  # Postgres returns Decimal; Decimal/float raises
        depletion_days = int(balance / avg) if avg > 0 and balance > 0 else None

        # Per-Luna usage + limit progress (hosting excluded by design: hosting
        # holds/charges never enter limit periods).
        agents = await _account_agents(db, account.id)
        limits = {
            l.agent_id: l for l in (
                await db.execute(
                    select(AgentCreditLimit).where(
                        AgentCreditLimit.agent_id.in_([a.id for a in agents] or [uuid.uuid4()])
                    )
                )
            ).scalars().all()
        }
        per_luna = []
        for a in agents:
            lim = limits.get(a.id)
            usage_rows = (
                await db.execute(
                    select(AgentLimitPeriod).where(
                        AgentLimitPeriod.agent_id == a.id,
                        AgentLimitPeriod.period_end > now,
                    )
                )
            ).scalars().all()
            cur = {r.period_kind: r for r in usage_rows}
            per_luna.append({
                "agent_id": str(a.id),
                "agent_name": a.name,
                "daily": {
                    "used_credits": (cur["daily"].settled_credits + cur["daily"].open_exposure_credits) if "daily" in cur else 0,
                    "limit_credits": lim.daily_limit_credits if lim else None,
                    "resets_at": cur["daily"].period_end.isoformat() if "daily" in cur else None,
                },
                "monthly": {
                    "used_credits": (cur["monthly"].settled_credits + cur["monthly"].open_exposure_credits) if "monthly" in cur else 0,
                    "limit_credits": lim.monthly_limit_credits if lim else None,
                    "resets_at": cur["monthly"].period_end.isoformat() if "monthly" in cur else None,
                },
                "warning_threshold_pct": lim.warning_threshold_pct if lim else None,
            })
        await db.commit()
        return {
            "range": {"since": since.isoformat(), "until": until.isoformat()},
            "used_credits": int(total),
            "today_credits": int(today_used),
            "month_credits": int(month_used),
            "remaining_credits": balance,
            "next_expiry_at": proj.next_expiry_at.isoformat() if proj.next_expiry_at else None,
            "trend": trend,
            "projected_depletion_days": depletion_days,
            "projection_is_estimate": True,
            "per_luna": per_luna,
        }


@router.get("/usage/breakdown")
async def usage_breakdown(
    by: str = Query("agent"),
    range: str = Query("28d"),
    start: str | None = None,
    end: str | None = None,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    if by not in BREAKDOWNS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"by must be one of {sorted(BREAKDOWNS)}")
    since, until = _range_bounds(range, start, end)
    dim = BREAKDOWNS[by]
    async with get_db_session() as db:
        # Credits live on the rated charge (one per logical call); events give
        # the dimension. A multi-event call maps its full charge to the call's
        # first event's dimension value — integer credits, no splitting.
        first_event = (
            select(
                BillableEvent.call_id.label("call_id"),
                func.min(BillableEvent.event_at).label("first_at"),
            )
            .where(BillableEvent.account_id == account.id)
            .group_by(BillableEvent.call_id)
            .subquery()
        )
        rows = (
            await db.execute(
                select(dim, func.sum(RatedCharge.credits), func.count(RatedCharge.id))
                .join(first_event, first_event.c.call_id == RatedCharge.logical_call_id)
                .join(BillableEvent, (BillableEvent.call_id == RatedCharge.logical_call_id)
                      & (BillableEvent.event_at == first_event.c.first_at))
                .where(
                    RatedCharge.account_id == account.id,
                    RatedCharge.created_at >= since,
                    RatedCharge.created_at < until,
                )
                .group_by(dim)
                .order_by(func.sum(RatedCharge.credits).desc())
            )
        ).all()

        # Resolve agent names (including tombstoned agents — history keeps them).
        names = {}
        if by == "agent":
            ids = [r[0] for r in rows if r[0]]
            if ids:
                names = {
                    a.id: a.name for a in (
                        await db.execute(select(Agent).where(Agent.id.in_(ids)))
                    ).scalars().all()
                }
        return [
            {
                "key": (names.get(r[0], str(r[0])) if by == "agent" else r[0]) or "(none)",
                "id": str(r[0]) if r[0] is not None else None,
                "credits": int(r[1]),
                "calls": int(r[2]),
            }
            for r in rows
        ]


async def _action_statement_rows(db, account_id: uuid.UUID, since: datetime,
                                 until: datetime, agent_id: uuid.UUID | None,
                                 limit: int, offset: int) -> list[dict]:
    """Actions = logical calls grouped by root action, newest first, with
    child call detail. Only credits, labels, models — never internals."""
    q = (
        select(BillableEvent, RatedCharge)
        .join(RatedCharge, RatedCharge.logical_call_id == BillableEvent.call_id)
        .where(
            BillableEvent.account_id == account_id,
            BillableEvent.event_at >= since,
            BillableEvent.event_at < until,
        )
        .order_by(BillableEvent.event_at.desc())
        .limit(2000)
    )
    if agent_id is not None:
        q = q.where(BillableEvent.agent_id == agent_id)
    pairs = (await db.execute(q)).all()

    agent_ids = {e.agent_id for e, _ in pairs if e.agent_id}
    names = {}
    if agent_ids:
        names = {
            a.id: a.name for a in (
                await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))
            ).scalars().all()
        }

    actions: dict[str, dict] = {}
    order: list[str] = []
    seen_calls: set[str] = set()
    for event, charge in pairs:
        root = event.root_action_id or event.call_id
        if root not in actions:
            order.append(root)
            actions[root] = {
                "root_action_id": root,
                "at": event.event_at.isoformat(),
                "agent_id": str(event.agent_id) if event.agent_id else None,
                "agent_name": names.get(event.agent_id),
                "label": ACTION_LABELS.get(event.root_action_type or "", None)
                          or (event.root_action_type or event.service),
                "service": event.service,
                "status": charge.charge_status,
                "credits": 0,
                "children": [],
            }
        a = actions[root]
        if event.call_id not in seen_calls:
            seen_calls.add(event.call_id)
            a["credits"] += charge.credits
        a["children"].append({
            "call_id": event.call_id,
            "at": event.event_at.isoformat(),
            "service": event.service,
            "plugin": event.plugin,
            "model": event.model,
            "credits": charge.credits,
            "status": charge.charge_status,
        })
    return [actions[k] for k in order][offset:offset + limit]


@router.get("/usage/actions")
async def usage_actions(
    range: str = Query("28d"),
    start: str | None = None,
    end: str | None = None,
    agent_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    since, until = _range_bounds(range, start, end)
    aid = uuid.UUID(agent_id) if agent_id else None
    async with get_db_session() as db:
        return await _action_statement_rows(db, account.id, since, until, aid, limit, offset)


@router.get("/usage/actions.csv")
async def usage_actions_csv(
    range: str = Query("28d"),
    start: str | None = None,
    end: str | None = None,
    agent_id: str | None = None,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    since, until = _range_bounds(range, start, end)
    aid = uuid.UUID(agent_id) if agent_id else None
    async with get_db_session() as db:
        rows = await _action_statement_rows(db, account.id, since, until, aid, 10_000, 0)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["time", "luna", "action", "service", "status", "credits"])
    for r in rows:
        writer.writerow([r["at"], r["agent_name"] or "", r["label"], r["service"],
                         r["status"], r["credits"]])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=luna-usage.csv"},
    )


# ── Statement: every wallet movement with a running balance ──────────────────

@router.get("/statement")
async def statement(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: tuple[User, Account] = Depends(require_active_account),
):
    _, account = auth
    async with get_db_session() as db:
        running = (
            func.sum(CreditLedgerPosting.credits)
            .over(order_by=CreditLedgerTransaction.seq)
            .label("running")
        )
        q = (
            select(CreditLedgerTransaction, CreditLedgerPosting.credits, running)
            .join(CreditLedgerPosting,
                  (CreditLedgerPosting.transaction_id == CreditLedgerTransaction.id)
                  & (CreditLedgerPosting.ledger_account == "customer_wallet"))
            .where(CreditLedgerTransaction.account_id == account.id)
            .order_by(CreditLedgerTransaction.seq.desc())
            .limit(limit).offset(offset)
        )
        rows = (await db.execute(q)).all()
        agent_ids = {t.agent_id for t, _, _ in rows if t.agent_id}
        names = {}
        if agent_ids:
            names = {
                a.id: a.name for a in (
                    await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))
                ).scalars().all()
            }
        return [
            {
                "at": t.created_at.isoformat(),
                "type": t.type,
                "reason": t.reason,
                "service": t.service,
                "agent_name": names.get(t.agent_id),
                "credits": int(delta),
                "balance_after": int(bal),
            }
            for t, delta, bal in rows
        ]


# ── Limits (owner-only mutation) ─────────────────────────────────────────────

class LimitUpdate(BaseModel):
    daily_limit_credits: int | None = Field(default=None, ge=0)
    monthly_limit_credits: int | None = Field(default=None, ge=0)
    warning_threshold_pct: int | None = Field(default=None, ge=1, le=100)


@router.put("/limits/{agent_id}", dependencies=[Depends(enforce_same_origin)])
async def set_limits(
    agent_id: str,
    body: LimitUpdate,
    auth: tuple[User, Account] = Depends(require_active_account),
):
    user, account = auth
    async with get_db_session() as db:
        await _require_owner(db, user, account)
        agent = (
            await db.execute(
                select(Agent).where(
                    Agent.id == uuid.UUID(agent_id),
                    Agent.account_id == account.id,
                    Agent.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if agent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        lim = await db.get(AgentCreditLimit, agent.id)
        if lim is None:
            lim = AgentCreditLimit(agent_id=agent.id)
            db.add(lim)
        lim.daily_limit_credits = body.daily_limit_credits
        lim.monthly_limit_credits = body.monthly_limit_credits
        lim.warning_threshold_pct = body.warning_threshold_pct
        lim.updated_by = user.id
        await db.commit()
        return {
            "agent_id": str(agent.id),
            "daily_limit_credits": lim.daily_limit_credits,
            "monthly_limit_credits": lim.monthly_limit_credits,
            "warning_threshold_pct": lim.warning_threshold_pct,
        }
