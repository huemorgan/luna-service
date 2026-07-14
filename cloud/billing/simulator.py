"""Pricing simulator (039/009): rerate real past usage under draft configs.

Read-only over production records — the engine SELECTs `billable_events`,
`credit_grants`, `stripe_payments`, `agent_hosting_periods` and writes only
its own `pricing_simulations` row. Replay goes through `rating.rate_call`,
the same single-margin single-ceil path production uses; there is no
parallel rating implementation.

Reproducibility: a run's manifest is snapshotted at creation — canonical
filter JSON + hash, the ORDERED billable-event ID list (+ hash), the maximum
ledger sequence, both config hashes, the provider-cost basis, transforms and
replay/funding modes, and the algorithm version. Rerun-by-manifest loads
events by the stored ID list, so late-arriving events or reconciled costs in
an `original_snapshot` run can never change the result.

No float ever enters the math: transform scenario values are decimal
strings parsed to exact rationals, config constants are ints, and every
division is a single explicit ceil.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import gcd

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing import rating
from cloud.billing.ledger import BURN_PRIORITY
from cloud.billing.models import (
    AgentHostingPeriod,
    BillableEvent,
    CommercialPricingVersion,
    CreditConsumption,
    CreditGrant,
    CreditLedgerTransaction,
    PricingSimulation,
    ProviderCostVersion,
    RatedCharge,
    StripePayment,
)
from cloud.billing.money import MICRO_USD_PER_CREDIT, rational_ceil, sum_rationals
from cloud.billing.rating import AttemptFacts
from cloud.billing.worker import enqueue, register_handler

ALGORITHM_VERSION = 1
SIMULATION_JOB = "pricing_sim"

# Interactive runs are bounded: a manifest stores every event ID it rates, so
# a run that would exceed this must narrow its filters instead of silently
# sampling (silent truncation would read as full coverage).
MAX_EVENTS = 200_000

DEFAULT_PERIOD_DAYS = 28

REPLAY_MODES = ("full_demand", "wallet_constrained")
FUNDING_MODES = ("actual_grants", "candidate_products")
COST_BASES = ("original_snapshot", "latest_reconciled", "selected_version")


class SimulationError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _sha256(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


# ── Exact decimal-string rationals ───────────────────────────────────────────

def parse_decimal_rational(value) -> tuple[int, int]:
    """`"0.50"` → (1, 2). Ints pass through; floats are rejected — the
    no-float invariant applies to simulation scenarios too."""
    if isinstance(value, bool) or isinstance(value, float):
        raise SimulationError(f"scenario value must be a decimal string or int, got {value!r}")
    if isinstance(value, int):
        if value < 0:
            raise SimulationError(f"scenario value must be nonnegative, got {value!r}")
        return value, 1
    if not isinstance(value, str):
        raise SimulationError(f"scenario value must be a decimal string or int, got {value!r}")
    text = value.strip()
    whole, dot, frac = text.partition(".")
    if not whole.isdigit() or (dot and (not frac or not frac.isdigit())):
        raise SimulationError(f"not a nonnegative decimal string: {value!r}")
    num = int(whole + frac)
    den = 10 ** len(frac)
    if num == 0:
        return 0, 1
    g = gcd(num, den)
    return num // g, den // g


def _mul_parts(parts: list[tuple[int, int]], num: int, den: int) -> list[tuple[int, int]]:
    return [(p_num * num, p_den * den) for p_num, p_den in parts]


# ── Transforms ───────────────────────────────────────────────────────────────

@dataclass
class Transforms:
    """Validated scenario transforms. All multipliers are exact rationals."""

    cost_multiplier: tuple[int, int] = (1, 1)
    # Most-specific-first override list: each entry may match on provider,
    # model and/or context; the first matching entry wins over the global.
    cost_multipliers: list[dict] = field(default_factory=list)
    volume_multiplier: tuple[int, int] = (1, 1)
    llm_constants: dict = field(default_factory=dict)  # partial override, int micro-USD

    def cost_factor(self, provider: str | None, model: str | None, context: str) -> tuple[int, int]:
        for entry in self.cost_multipliers:
            if entry.get("provider") not in (None, provider):
                continue
            if entry.get("model") not in (None, model):
                continue
            if entry.get("context") not in (None, context):
                continue
            return entry["_rational"]
        return self.cost_multiplier


def parse_transforms(raw: dict | None) -> Transforms:
    raw = raw or {}
    unknown = set(raw) - {"cost_multiplier", "cost_multipliers", "volume_multiplier", "llm_constants"}
    if unknown:
        raise SimulationError(f"unknown transform keys: {sorted(unknown)}")
    t = Transforms()
    if "cost_multiplier" in raw:
        t.cost_multiplier = parse_decimal_rational(raw["cost_multiplier"])
    for i, entry in enumerate(raw.get("cost_multipliers") or []):
        if not isinstance(entry, dict) or "multiplier" not in entry:
            raise SimulationError(f"cost_multipliers[{i}] needs a multiplier")
        parsed = dict(entry)
        parsed["_rational"] = parse_decimal_rational(entry["multiplier"])
        t.cost_multipliers.append(parsed)
    if "volume_multiplier" in raw:
        t.volume_multiplier = parse_decimal_rational(raw["volume_multiplier"])
    constants = raw.get("llm_constants") or {}
    for ctx, tiers in constants.items():
        if ctx not in ("agent", "direct", "forge") or not isinstance(tiers, dict):
            raise SimulationError(f"llm_constants.{ctx} invalid")
        for tier, value in tiers.items():
            if tier not in ("top", "mid") or not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise SimulationError(f"llm_constants.{ctx}.{tier} must be a nonnegative int")
    t.llm_constants = constants
    return t


def _margin_for(config: dict, overrides: dict, context: str, tier: str) -> int:
    override = ((overrides.get(context) or {}).get(tier))
    if override is not None:
        return override
    return rating.margin_micro_usd(config, context, tier)


# ── Manifest ─────────────────────────────────────────────────────────────────

def canonical_filters(filters: dict | None) -> dict:
    """Normalize the filter set so its hash is stable across dict ordering."""
    filters = filters or {}
    unknown = set(filters) - {
        "period_start", "period_end", "account_ids", "agent_ids",
        "services", "providers", "models", "contexts",
    }
    if unknown:
        raise SimulationError(f"unknown filter keys: {sorted(unknown)}")
    out: dict = {}
    end = filters.get("period_end")
    start = filters.get("period_start")
    end_dt = _aware(datetime.fromisoformat(end)) if end else _utcnow()
    start_dt = _aware(datetime.fromisoformat(start)) if start else end_dt - timedelta(days=DEFAULT_PERIOD_DAYS)
    if start_dt >= end_dt:
        raise SimulationError("period_start must precede period_end")
    out["period_start"] = start_dt.isoformat()
    out["period_end"] = end_dt.isoformat()
    for key in ("account_ids", "agent_ids", "services", "providers", "models", "contexts"):
        values = filters.get(key)
        if values:
            out[key] = sorted(str(v) for v in values)
    return out


async def _select_event_ids(session: AsyncSession, filters: dict) -> list[str]:
    """Deterministic event selection: recorded usage in the window, ordered by
    (event_at, call, attempt, id) — the manifest freezes this list forever."""
    stmt = (
        select(BillableEvent.id)
        .where(
            BillableEvent.status == "recorded",
            BillableEvent.event_at >= datetime.fromisoformat(filters["period_start"]),
            BillableEvent.event_at < datetime.fromisoformat(filters["period_end"]),
        )
        .order_by(
            BillableEvent.event_at.asc(),
            BillableEvent.call_id.asc(),
            BillableEvent.attempt_number.asc(),
            BillableEvent.id.asc(),
        )
    )
    if filters.get("account_ids"):
        stmt = stmt.where(BillableEvent.account_id.in_([uuid.UUID(a) for a in filters["account_ids"]]))
    if filters.get("agent_ids"):
        stmt = stmt.where(BillableEvent.agent_id.in_([uuid.UUID(a) for a in filters["agent_ids"]]))
    if filters.get("services"):
        stmt = stmt.where(BillableEvent.service.in_(filters["services"]))
    if filters.get("providers"):
        stmt = stmt.where(BillableEvent.provider.in_(filters["providers"]))
    if filters.get("models"):
        stmt = stmt.where(BillableEvent.model.in_(filters["models"]))
    if filters.get("contexts"):
        stmt = stmt.where(BillableEvent.context.in_(filters["contexts"]))
    ids = [str(i) for i in (await session.execute(stmt)).scalars().all()]
    if len(ids) > MAX_EVENTS:
        raise SimulationError(
            f"{len(ids)} events exceed the {MAX_EVENTS} cap — narrow the filters"
        )
    return ids


async def _version_or_error(session: AsyncSession, version_id: uuid.UUID) -> CommercialPricingVersion:
    version = await session.get(CommercialPricingVersion, version_id)
    if version is None:
        raise SimulationError(f"commercial version {version_id} not found")
    return version


async def build_manifest(
    session: AsyncSession,
    *,
    filters: dict | None,
    baseline_version_id: uuid.UUID,
    candidate_version_id: uuid.UUID,
    provider_cost_basis: str = "original_snapshot",
    provider_cost_version_id: uuid.UUID | None = None,
    transforms: dict | None = None,
    replay_mode: str = "full_demand",
    funding_mode: str = "actual_grants",
    now: datetime | None = None,
) -> dict:
    """Snapshot everything a rerun needs. Called once at creation time."""
    if replay_mode not in REPLAY_MODES:
        raise SimulationError(f"replay_mode must be one of {REPLAY_MODES}")
    if funding_mode not in FUNDING_MODES:
        raise SimulationError(f"funding_mode must be one of {FUNDING_MODES}")
    if provider_cost_basis not in COST_BASES:
        raise SimulationError(f"provider_cost_basis must be one of {COST_BASES}")
    parsed = parse_transforms(transforms)  # validate now, fail before anything persists
    if replay_mode == "wallet_constrained" and parsed.volume_multiplier != (1, 1):
        # Volume scaling is an aggregate approximation; wallet blocking is
        # volume-dependent, so mixing them would fabricate block decisions.
        raise SimulationError("volume_multiplier is only valid with full_demand replay")

    baseline = await _version_or_error(session, baseline_version_id)
    candidate = await _version_or_error(session, candidate_version_id)

    filters = canonical_filters(filters)
    event_ids = await _select_event_ids(session, filters)

    if provider_cost_basis == "original_snapshot":
        provider_cost_version_id = None  # stored attempt costs, no rate table
    if provider_cost_basis == "latest_reconciled":
        # Resolved once, here: the manifest pins the version so reconciled
        # costs published later can never change this run.
        provider_cost_version_id = await rating.resolve_provider_cost_version(
            session, now or _utcnow()
        )
    if provider_cost_basis == "selected_version" and provider_cost_version_id is None:
        raise SimulationError("selected_version basis requires provider_cost_version_id")
    if provider_cost_version_id is not None:
        pcv = await session.get(ProviderCostVersion, provider_cost_version_id)
        if pcv is None or pcv.status != "published":
            raise SimulationError("provider cost version must exist and be published")

    max_seq = (
        await session.execute(select(func.coalesce(func.max(CreditLedgerTransaction.seq), 0)))
    ).scalar_one()

    return {
        "algorithm_version": ALGORITHM_VERSION,
        "filters": filters,
        "filters_hash": _sha256(filters),
        "event_ids": event_ids,
        "event_ids_hash": _sha256(event_ids),
        "event_count": len(event_ids),
        "max_ledger_seq": int(max_seq),
        "baseline_version_id": str(baseline.id),
        "baseline_config_hash": baseline.config_hash,
        # Full config snapshots: drafts are mutable, so a rerun must rate
        # against what the manifest saw, not what the draft became.
        "baseline_config": baseline.config_json,
        "candidate_version_id": str(candidate.id),
        "candidate_config_hash": candidate.config_hash,
        "candidate_config": candidate.config_json,
        "provider_cost_basis": provider_cost_basis,
        "provider_cost_version_id": str(provider_cost_version_id) if provider_cost_version_id else None,
        "transforms": transforms or {},
        "replay_mode": replay_mode,
        "funding_mode": funding_mode,
    }


async def create_simulation(
    session: AsyncSession,
    *,
    filters: dict | None = None,
    baseline_version_id: uuid.UUID | None = None,
    candidate_version_id: uuid.UUID | None = None,
    provider_cost_basis: str = "original_snapshot",
    provider_cost_version_id: uuid.UUID | None = None,
    transforms: dict | None = None,
    replay_mode: str = "full_demand",
    funding_mode: str = "actual_grants",
    created_by: uuid.UUID | None = None,
    manifest: dict | None = None,
) -> PricingSimulation:
    """Create the simulation row + its durable job. Pass `manifest` to rerun
    an existing manifest verbatim (reproducibility path)."""
    if manifest is None:
        if baseline_version_id is None or candidate_version_id is None:
            raise SimulationError("baseline and candidate versions are required")
        manifest = await build_manifest(
            session,
            filters=filters,
            baseline_version_id=baseline_version_id,
            candidate_version_id=candidate_version_id,
            provider_cost_basis=provider_cost_basis,
            provider_cost_version_id=provider_cost_version_id,
            transforms=transforms,
            replay_mode=replay_mode,
            funding_mode=funding_mode,
        )
    sim = PricingSimulation(
        created_by=created_by,
        filters=manifest["filters"],
        baseline_version_id=uuid.UUID(manifest["baseline_version_id"]),
        candidate_version_id=uuid.UUID(manifest["candidate_version_id"]),
        provider_cost_basis=manifest["provider_cost_basis"],
        transforms=manifest["transforms"],
        config_hash=_sha256(
            {k: v for k, v in manifest.items() if k not in ("event_ids",)}
        ),
        manifest=manifest,
        state="pending",
    )
    session.add(sim)
    await session.flush()
    await enqueue(
        session,
        job_type=SIMULATION_JOB,
        payload={"simulation_id": str(sim.id)},
        dedupe_key=f"pricing_sim:{sim.id}",
    )
    return sim


# ── Replay ───────────────────────────────────────────────────────────────────

@dataclass
class LogicalCall:
    operation_id: str
    account_id: uuid.UUID
    context: str
    event_at: datetime
    attempts: list[AttemptFacts]
    models: list[str | None]
    stored_costs: list[int]  # per-attempt vendor_cost_micro_usd as recorded


def _operation_id(event: BillableEvent) -> str:
    # source_idempotency_key is "{operation_id}:{attempt_number}".
    return event.source_idempotency_key.rsplit(":", 1)[0]


async def _load_calls(
    session: AsyncSession, event_ids: list[str]
) -> tuple[list[LogicalCall], int]:
    """Group manifest events into logical calls. The billable flag is not
    persisted on events, so it is reconstructed: within a call whose rated
    outcome was accepted (status_code < 400, or no rated charge but usage
    present), the final attempt is billable and earlier ones Luna-absorbed."""
    if not event_ids:
        return [], 0
    events: list[BillableEvent] = []
    for i in range(0, len(event_ids), 5_000):  # bounded IN() batches
        chunk = [uuid.UUID(e) for e in event_ids[i : i + 5_000]]
        events.extend(
            (await session.execute(select(BillableEvent).where(BillableEvent.id.in_(chunk))))
            .scalars().all()
        )
    by_id = {str(e.id): e for e in events}
    ordered = [by_id[e] for e in event_ids if e in by_id]
    missing = len(event_ids) - len(ordered)

    groups: dict[str, list[BillableEvent]] = {}
    for event in ordered:
        groups.setdefault(_operation_id(event), []).append(event)

    op_ids = list(groups)
    accepted: dict[str, bool] = {}
    for i in range(0, len(op_ids), 5_000):
        chunk = op_ids[i : i + 5_000]
        rows = (
            await session.execute(
                select(RatedCharge.logical_call_id, RatedCharge.rule_snapshot).where(
                    RatedCharge.logical_call_id.in_(chunk)
                )
            )
        ).all()
        for op_id, snapshot in rows:
            status_code = (snapshot or {}).get("status_code")
            accepted[op_id] = status_code is None or int(status_code) < 400

    calls: list[LogicalCall] = []
    for op_id, group in groups.items():
        group.sort(key=lambda e: (e.attempt_number, str(e.id)))
        ok = accepted.get(op_id)
        if ok is None:  # no rated charge — accepted iff usage was captured
            ok = any(e.quantity_json for e in group)
        last = group[-1].attempt_number
        attempts = [
            AttemptFacts(
                provider=e.provider or "",
                model=e.model,
                dimensions={
                    k: v for k, v in (e.quantity_json or {}).items()
                    if isinstance(v, int) and not isinstance(v, bool)
                },
                billable=bool(ok and e.attempt_number == last),
                attempt_number=e.attempt_number,
                cost_source=e.cost_source,
            )
            for e in group
        ]
        calls.append(
            LogicalCall(
                operation_id=op_id,
                account_id=group[0].account_id,
                context=group[0].context,
                event_at=_aware(group[0].event_at),
                attempts=attempts,
                models=[e.model for e in group],
                stored_costs=[e.vendor_cost_micro_usd for e in group],
            )
        )
    calls.sort(key=lambda c: (c.event_at, c.operation_id))
    return calls, missing


def _rate_side(
    call: LogicalCall,
    *,
    config: dict,
    rates: dict[tuple[str, str, str], tuple[int, int]] | None,
    transforms: Transforms,
) -> dict:
    """Rate one logical call under one config. rates=None → original
    snapshot basis (stored integer attempt costs, still one final ceil)."""
    model = next((m for m in reversed(call.models) if m), None)
    tier = rating.model_tier(config, model)
    if tier is None:
        return {"unpriced": True, "credits": 0, "vendor_micro_usd": 0,
                "margin_micro_usd": 0, "rounding_micro_usd": 0,
                "absorbed_micro_usd": 0, "unrated_dimensions": []}
    margin = _margin_for(config, transforms.llm_constants, call.context, tier)

    if rates is None:
        factor = transforms.cost_factor(call.attempts[0].provider or None, model, call.context)
        billable_parts: list[tuple[int, int]] = []
        absorbed_parts: list[tuple[int, int]] = []
        for attempt, stored in zip(call.attempts, call.stored_costs):
            part = (stored * factor[0], factor[1])
            (billable_parts if attempt.billable else absorbed_parts).append(part)
        num, den = sum_rationals(billable_parts or [(0, 1)])
        vendor_micro = rational_ceil(num, den)
        credits = rational_ceil(num + margin * den, den * MICRO_USD_PER_CREDIT)
        absorbed = rational_ceil(*sum_rationals(absorbed_parts or [(0, 1)]))
        return {"unpriced": False, "credits": credits, "vendor_micro_usd": vendor_micro,
                "margin_micro_usd": margin,
                "rounding_micro_usd": credits * MICRO_USD_PER_CREDIT - vendor_micro - margin,
                "absorbed_micro_usd": absorbed, "unrated_dimensions": []}

    factor = transforms.cost_factor(call.attempts[0].provider or None, model, call.context)
    scaled_rates = rates
    if factor != (1, 1):
        scaled_rates = {
            key: (num * factor[0], den * factor[1]) for key, (num, den) in rates.items()
        }
    result = rating.rate_call(scaled_rates, margin_micro=margin, attempts=call.attempts)
    return {
        "unpriced": False,
        "credits": result.credits,
        "vendor_micro_usd": result.vendor_micro_usd,
        "margin_micro_usd": result.margin_micro_usd,
        "rounding_micro_usd": result.rounding_micro_usd,
        "absorbed_micro_usd": result.luna_absorbed_micro_usd,
        "unrated_dimensions": result.unrated_dimensions,
    }


# ── Wallet-constrained replay ────────────────────────────────────────────────

@dataclass
class SimLot:
    lot_id: str
    category: str            # bonus|gift|free|paid|topup
    credits: int
    remaining: int
    effective_at: datetime
    expires_at: datetime | None
    cash_backed: bool        # consumed credits count toward cash basis

    @property
    def priority(self) -> int:
        return BURN_PRIORITY[self.category]


class SimWallet:
    """In-memory wallet replay. Ordering rules mirror the ledger: expiration
    is exclusive at expires_at (a lot expiring at T is unusable at T), grant
    activation precedes authorization at the same instant, burn order is
    priority then earliest expiry (never-expiring last) then effective_at."""

    def __init__(self, lots: list[SimLot]):
        self.pending = sorted(lots, key=lambda l: (l.effective_at, l.lot_id))
        self.active: list[SimLot] = []
        self.debt = 0
        self.consumed_cash_credits = 0
        self.consumed_credits = 0
        self.subsidy_credits = 0  # consumed from non-cash lots
        self.hit_zero = False

    def _advance(self, now: datetime) -> None:
        while self.pending and _aware(self.pending[0].effective_at) <= now:
            self.active.append(self.pending.pop(0))
        self.active = [
            lot for lot in self.active
            if lot.expires_at is None or _aware(lot.expires_at) > now
        ]

    def balance(self, now: datetime) -> int:
        self._advance(now)
        return sum(lot.remaining for lot in self.active) - self.debt

    def charge(self, credits: int, now: datetime) -> bool:
        """Authorize-then-settle one call. Returns False when blocked
        (posted balance <= 0 — the enforce rule); a charge that passes the
        gate posts in full, even into debt."""
        self._advance(now)
        balance = sum(lot.remaining for lot in self.active) - self.debt
        if balance <= 0:
            self.hit_zero = True
            return False
        order = sorted(
            self.active,
            key=lambda l: (
                l.priority,
                l.expires_at is None,
                _aware(l.expires_at) or now,
                _aware(l.effective_at),
                l.lot_id,
            ),
        )
        left = credits
        for lot in order:
            if left <= 0:
                break
            take = min(lot.remaining, left)
            lot.remaining -= take
            left -= take
            self.consumed_credits += take
            if lot.cash_backed:
                self.consumed_cash_credits += take
            else:
                self.subsidy_credits += take
        if left > 0:
            self.debt += left
        return True


async def _actual_lots(
    session: AsyncSession, account_ids: list[uuid.UUID], period_start: datetime
) -> dict[uuid.UUID, list[SimLot]]:
    """Historical lots per account, with remainders rewound to period_start
    (consumption before the window is subtracted; the window itself replays)."""
    if not account_ids:
        return {}
    grants = (
        await session.execute(
            select(CreditGrant).where(
                CreditGrant.account_id.in_(account_ids),
                CreditGrant.status != "reversed",
            )
        )
    ).scalars().all()
    consumed_before = dict(
        (
            await session.execute(
                select(CreditConsumption.grant_id, func.coalesce(func.sum(CreditConsumption.credits), 0))
                .join(
                    CreditLedgerTransaction,
                    CreditConsumption.charge_transaction_id == CreditLedgerTransaction.id,
                )
                .where(
                    CreditConsumption.account_id.in_(account_ids),
                    CreditConsumption.grant_id.is_not(None),
                    CreditLedgerTransaction.created_at < period_start,
                )
                .group_by(CreditConsumption.grant_id)
            )
        ).all()
    )
    lots: dict[uuid.UUID, list[SimLot]] = {}
    for grant in grants:
        remaining = grant.original_credits - int(consumed_before.get(grant.id, 0))
        if remaining <= 0:
            continue
        lots.setdefault(grant.account_id, []).append(
            SimLot(
                lot_id=str(grant.id),
                category=grant.visible_category,
                credits=grant.original_credits,
                remaining=remaining,
                effective_at=_aware(grant.effective_at),
                expires_at=_aware(grant.expires_at),
                cash_backed=grant.cash_paid_micro_usd > 0 or grant.visible_category in ("paid", "topup"),
            )
        )
    return lots


async def _candidate_lots(
    session: AsyncSession,
    account_ids: list[uuid.UUID],
    candidate_config: dict,
    period_end: datetime,
) -> tuple[dict[uuid.UUID, list[SimLot]], int]:
    """Hypothetical lots: every historical successful pretax payment re-granted
    under the candidate product mapping. Lots are full-size (pre-window
    consumption against hypothetical lots is unknowable — results carry the
    funding-mode label for exactly this reason). Returns (lots, unmapped)."""
    from cloud.billing.stripe_webhooks import add_months_clamped

    if not account_ids:
        return {}, 0
    products = {p["key"]: p for p in candidate_config.get("products") or []}
    payments = (
        await session.execute(
            select(StripePayment).where(
                StripePayment.account_id.in_(account_ids),
                StripePayment.created_at < period_end,
            )
        )
    ).scalars().all()
    lots: dict[uuid.UUID, list[SimLot]] = {}
    unmapped = 0
    for payment in payments:
        product = products.get(payment.product_key)
        if product is None:
            unmapped += 1
            continue
        start = _aware(payment.created_at)
        acct = lots.setdefault(payment.account_id, [])
        if product["kind"] == "topup":
            # Historical pretax money buys candidate top-up credits 1:1
            # (1 credit = $0.01, paid = payment × 100 — the catalog rule).
            acct.append(SimLot(
                lot_id=f"{payment.payment_ref}:topup",
                category="topup",
                credits=payment.pretax_amount_cents,
                remaining=payment.pretax_amount_cents,
                effective_at=start, expires_at=None, cash_backed=True,
            ))
            continue
        if product.get("interval") == "year":
            monthly_paid = product["monthly_paid_lot_credits"]
            monthly_bonus = product.get("monthly_bonus_lot_credits") or 0
            boundaries = [add_months_clamped(start, i) for i in range(13)]
            for i in range(12):
                acct.append(SimLot(
                    lot_id=f"{payment.payment_ref}:paid:{i}", category="paid",
                    credits=monthly_paid, remaining=monthly_paid,
                    effective_at=boundaries[i], expires_at=boundaries[i + 1],
                    cash_backed=True,
                ))
                if monthly_bonus > 0:
                    acct.append(SimLot(
                        lot_id=f"{payment.payment_ref}:bonus:{i}", category="bonus",
                        credits=monthly_bonus, remaining=monthly_bonus,
                        effective_at=boundaries[i], expires_at=boundaries[i + 1],
                        cash_backed=False,
                    ))
            gift = product.get("yearly_gift_credits") or 0
            if gift > 0:
                acct.append(SimLot(
                    lot_id=f"{payment.payment_ref}:gift", category="gift",
                    credits=gift, remaining=gift,
                    effective_at=start, expires_at=boundaries[12], cash_backed=False,
                ))
        else:
            end = add_months_clamped(start, 1)
            acct.append(SimLot(
                lot_id=f"{payment.payment_ref}:paid", category="paid",
                credits=product["paid_credits"], remaining=product["paid_credits"],
                effective_at=start, expires_at=end, cash_backed=True,
            ))
            bonus = product.get("bonus_credits") or 0
            if bonus > 0:
                acct.append(SimLot(
                    lot_id=f"{payment.payment_ref}:bonus", category="bonus",
                    credits=bonus, remaining=bonus,
                    effective_at=start, expires_at=end, cash_backed=False,
                ))
    return lots, unmapped


# ── Aggregation and execution ────────────────────────────────────────────────

def _empty_side() -> dict:
    return {
        "credits": 0, "face_value_micro_usd": 0, "cash_basis_micro_usd": None,
        "vendor_micro_usd": 0, "margin_micro_usd": 0, "rounding_micro_usd": 0,
        "luna_absorbed_micro_usd": 0, "gross_profit_face_micro_usd": 0,
        "gross_profit_cash_micro_usd": None, "subsidy_credits": None,
        "hosting_credits": 0, "unpriced_calls": 0, "blocked_calls": 0,
        "blocked_credits": 0, "accounts_hit_zero": 0, "accounts_in_debt": 0,
        "rated_calls": 0, "unrated_dimensions": [],
    }


def _scale_side(side: dict, num: int, den: int) -> None:
    """Volume transform: exact rational scaling of the aggregate totals with
    one ceil per figure — per-call ceil semantics are already inside the
    unscaled totals, so scaling the sum models proportional extra demand."""
    if (num, den) == (1, 1):
        return
    for key in ("credits", "face_value_micro_usd", "vendor_micro_usd",
                "margin_micro_usd", "rounding_micro_usd", "luna_absorbed_micro_usd",
                "blocked_credits"):
        if side.get(key) is not None:
            side[key] = rational_ceil(side[key] * num, den)
    if side.get("cash_basis_micro_usd") is not None:
        side["cash_basis_micro_usd"] = rational_ceil(side["cash_basis_micro_usd"] * num, den)


def _finish_side(side: dict) -> None:
    side["face_value_micro_usd"] = side["credits"] * MICRO_USD_PER_CREDIT
    side["gross_profit_face_micro_usd"] = (
        side["face_value_micro_usd"] - side["vendor_micro_usd"] - side["luna_absorbed_micro_usd"]
    )
    if side["cash_basis_micro_usd"] is not None:
        side["gross_profit_cash_micro_usd"] = (
            side["cash_basis_micro_usd"] - side["vendor_micro_usd"] - side["luna_absorbed_micro_usd"]
        )


async def _hosting_credits(
    session: AsyncSession, config: dict, account_ids: list[uuid.UUID] | None,
    period_start: datetime, period_end: datetime,
) -> int:
    """Hosting revenue is pure config replay: candidate price × the number of
    hosting periods that started in the window."""
    stmt = select(func.count(AgentHostingPeriod.id)).where(
        AgentHostingPeriod.starts_at >= period_start,
        AgentHostingPeriod.starts_at < period_end,
        AgentHostingPeriod.state.in_(["paid", "active", "ended", "payment_due"]),
    )
    if account_ids:
        stmt = stmt.where(AgentHostingPeriod.account_id.in_(account_ids))
    periods = (await session.execute(stmt)).scalar_one()
    price = ((config.get("hosting") or {}).get("price_credits")) or 0
    return int(periods) * price


async def run_simulation(session: AsyncSession, sim: PricingSimulation) -> dict:
    """Execute one simulation from its manifest. Pure read → compute → one
    result dict; the caller persists it (never partially)."""
    manifest = sim.manifest
    transforms = parse_transforms(manifest.get("transforms"))
    filters = manifest["filters"]
    period_start = datetime.fromisoformat(filters["period_start"])
    period_end = datetime.fromisoformat(filters["period_end"])

    # Rate against the manifest's config snapshots — never the live rows,
    # which may be drafts that changed since the manifest was built.
    baseline_config = manifest["baseline_config"]
    candidate_config = manifest["candidate_config"]

    rates = None
    if manifest["provider_cost_version_id"]:
        rates = await rating.load_provider_rates(
            session, uuid.UUID(manifest["provider_cost_version_id"])
        )

    calls, missing_events = await _load_calls(session, manifest["event_ids"])
    account_ids = sorted({c.account_id for c in calls}, key=str)

    sides = {"baseline": _empty_side(), "candidate": _empty_side()}
    configs = {"baseline": baseline_config, "candidate": candidate_config}
    # Transforms model the candidate scenario only; the baseline is the
    # untouched control.
    side_transforms = {"baseline": Transforms(), "candidate": transforms}

    per_account: dict[str, dict] = {}
    per_call: dict[str, dict[str, dict]] = {"baseline": {}, "candidate": {}}
    unrated: set[str] = set()

    for call in calls:
        acct = per_account.setdefault(
            str(call.account_id),
            {"account_id": str(call.account_id), "baseline_credits": 0,
             "candidate_credits": 0, "baseline_blocked": 0, "candidate_blocked": 0},
        )
        for side_name in ("baseline", "candidate"):
            rated = _rate_side(
                call, config=configs[side_name], rates=rates,
                transforms=side_transforms[side_name],
            )
            per_call[side_name][call.operation_id] = rated
            side = sides[side_name]
            if rated["unpriced"]:
                side["unpriced_calls"] += 1
                continue
            side["rated_calls"] += 1
            unrated.update(rated["unrated_dimensions"])

    wallet_meta: dict[str, dict] = {}
    if manifest["replay_mode"] == "wallet_constrained":
        unmapped_payments = 0
        if manifest["funding_mode"] == "actual_grants":
            # Two independent loads: SimLot remainders mutate during replay,
            # so baseline and candidate must never share lot objects.
            baseline_lots = await _actual_lots(session, account_ids, period_start)
            candidate_lots = await _actual_lots(session, account_ids, period_start)
        else:
            baseline_lots, unmapped_b = await _candidate_lots(
                session, account_ids, baseline_config, period_end
            )
            candidate_lots, unmapped_c = await _candidate_lots(
                session, account_ids, candidate_config, period_end
            )
            unmapped_payments = max(unmapped_b, unmapped_c)
        wallet_meta = {"unmapped_payments": unmapped_payments}

        for side_name, lots_map in (("baseline", baseline_lots), ("candidate", candidate_lots)):
            side = sides[side_name]
            wallets = {
                account_id: SimWallet(lots_map.get(account_id, []))
                for account_id in account_ids
            }
            # Deterministic demand order: (effective_timestamp, stable id).
            # Grant activation/expiry happen inside the wallet at each
            # instant, before the charge is authorized.
            for call in calls:
                rated = per_call[side_name].get(call.operation_id)
                if rated is None or rated["unpriced"]:
                    continue
                wallet = wallets[call.account_id]
                if wallet.charge(rated["credits"], call.event_at):
                    side["credits"] += rated["credits"]
                    side["vendor_micro_usd"] += rated["vendor_micro_usd"]
                    side["margin_micro_usd"] += rated["margin_micro_usd"]
                    side["rounding_micro_usd"] += rated["rounding_micro_usd"]
                    side["luna_absorbed_micro_usd"] += rated["absorbed_micro_usd"]
                    key = f"{side_name}_credits"
                    per_account[str(call.account_id)][key] += rated["credits"]
                else:
                    side["blocked_calls"] += 1
                    side["blocked_credits"] += rated["credits"]
                    per_account[str(call.account_id)][f"{side_name}_blocked"] += rated["credits"]
            side["cash_basis_micro_usd"] = sum(
                w.consumed_cash_credits for w in wallets.values()
            ) * MICRO_USD_PER_CREDIT
            side["subsidy_credits"] = sum(w.subsidy_credits for w in wallets.values())
            side["accounts_hit_zero"] = sum(1 for w in wallets.values() if w.hit_zero)
            side["accounts_in_debt"] = sum(1 for w in wallets.values() if w.debt > 0)
    else:
        for call in calls:
            for side_name in ("baseline", "candidate"):
                rated = per_call[side_name].get(call.operation_id)
                if rated is None or rated["unpriced"]:
                    continue
                side = sides[side_name]
                side["credits"] += rated["credits"]
                side["vendor_micro_usd"] += rated["vendor_micro_usd"]
                side["margin_micro_usd"] += rated["margin_micro_usd"]
                side["rounding_micro_usd"] += rated["rounding_micro_usd"]
                side["luna_absorbed_micro_usd"] += rated["absorbed_micro_usd"]
                per_account[str(call.account_id)][f"{side_name}_credits"] += rated["credits"]

    for side_name in ("baseline", "candidate"):
        side = sides[side_name]
        side["hosting_credits"] = await _hosting_credits(
            session, configs[side_name],
            [uuid.UUID(a) for a in filters.get("account_ids", [])] or None,
            period_start, period_end,
        )
        _scale_side(side, *side_transforms[side_name].volume_multiplier)
        _finish_side(side)

    accounts = sorted(
        per_account.values(),
        key=lambda a: a["candidate_credits"] - a["baseline_credits"],
    )
    delta = {
        key: (sides["candidate"][key] - sides["baseline"][key])
        if isinstance(sides["candidate"][key], int) and isinstance(sides["baseline"][key], int)
        else None
        for key in _empty_side()
        if key != "unrated_dimensions"
    }

    result = {
        "algorithm_version": ALGORITHM_VERSION,
        "replay_mode": manifest["replay_mode"],
        "funding_mode": manifest["funding_mode"],
        "provider_cost_basis": manifest["provider_cost_basis"],
        "event_count": manifest["event_count"],
        "missing_events": missing_events,  # deleted since the manifest — surfaced, never guessed
        "logical_calls": len(calls),
        "accounts": len(account_ids),
        "baseline": sides["baseline"],
        "candidate": sides["candidate"],
        "delta": delta,
        # winners pay less under the candidate; losers pay more.
        "winners": accounts[:20],
        "losers": accounts[-20:][::-1],
        "per_account": accounts,
        "unrated_dimensions": sorted(unrated),
        "wallet": wallet_meta,
        # Face value is never cash revenue — cash basis comes only from
        # consumed cash-backed lots in wallet-constrained replay.
        "labels": {
            "face_value": "credit face value (not cash revenue)",
            "cash_basis": "consumed cash-backed lots only"
            if manifest["replay_mode"] == "wallet_constrained"
            else "unavailable in full_demand replay",
        },
    }
    result["result_hash"] = _sha256(result)
    return result


async def _handle_pricing_sim(session: AsyncSession, job) -> dict:
    sim = await session.get(PricingSimulation, uuid.UUID(job.payload["simulation_id"]))
    if sim is None:
        raise SimulationError("simulation row not found")
    if sim.state == "cancelled":
        # A cancelled run never publishes anything — not even partials.
        return {"state": "cancelled"}
    if sim.state == "succeeded" and sim.result is not None:
        return {"state": "succeeded", "result_hash": sim.result.get("result_hash")}
    sim.state = "running"
    await session.flush()
    try:
        result = await run_simulation(session, sim)
    except SimulationError as exc:
        # Configuration errors are terminal, not retryable: publish the
        # failure on the row and succeed the job so it never dead-letters.
        sim.state = "failed"
        sim.result = {"error": str(exc)}
        await session.flush()
        return {"state": "failed", "error": str(exc)}
    if sim.state == "cancelled":  # cancelled mid-compute — drop the result
        return {"state": "cancelled"}
    sim.state = "succeeded"
    sim.result = result
    await session.flush()
    return {"state": "succeeded", "result_hash": result["result_hash"]}


register_handler(SIMULATION_JOB, _handle_pricing_sim)


def result_csv(sim: PricingSimulation) -> str:
    """Per-account CSV of a finished run."""
    rows = ["account_id,baseline_credits,candidate_credits,delta_credits,baseline_blocked,candidate_blocked"]
    for acct in (sim.result or {}).get("per_account", []):
        rows.append(
            f"{acct['account_id']},{acct['baseline_credits']},{acct['candidate_credits']},"
            f"{acct['candidate_credits'] - acct['baseline_credits']},"
            f"{acct.get('baseline_blocked', 0)},{acct.get('candidate_blocked', 0)}"
        )
    return "\n".join(rows) + "\n"
