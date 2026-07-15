"""Gateway billing enforcement (039/004).

Managed (platform-keyed) requests flow through here around the upstream call:

    prepare()  — classify the route, resolve the billing identity and the
                 snapshotted pricing/cost versions, estimate exposure, and in
                 enforce mode open a ledger hold BEFORE any provider contact.
    finalize() — after the response (streamed or not): persist one
                 billable_event per provider attempt plus the rated charge,
                 and enqueue the durable settle/release outbox job.

Mode semantics (`CLOUD_BILLING_MODE`):

    off      — billing is bypassed entirely (no reads, no writes).
    observe  — events + rated charges recorded; would-block decisions from
               classification are recorded; no wallet reads or decisions.
    shadow   — observe, plus the real authorization decision is computed
               against the live wallet inside a rolled-back savepoint (no
               customer effect). Deviation from the plan's "isolated shadow
               wallet" — documented in the 004 execution summary.
    enforce  — holds, blocks, settles. Billing-store failure fails closed
               (`billing_temporarily_unavailable`) in this mode only.

The 402 block contract is frozen — Luna-side handling (039/003) keys off
`error.code`:

    credits_exhausted | luna_daily_limit | luna_monthly_limit |
    hosting_payment_due | sku_unpriced | exposure_limit |
    billing_temporarily_unavailable

Block messages are customer-safe: they never mention tiers, margins,
classification or any other pricing internals. No prompt, output, credential
or personal content ever enters billing rows.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing import ledger, modes, rating
from cloud.billing import worker as billing_worker
from cloud.billing.models import AgentHostingPeriod, BillableEvent, RatedCharge
from cloud.billing.rating import AttemptFacts, RatingUnavailable
from cloud.config import get_settings
from cloud.db import session as db_session
from cloud.db.models import Agent
from cloud.gateway import adapters as usage_adapters
from cloud.gateway import route_catalog

log = logging.getLogger("gateway.billing")

MODES = ("off", "observe", "shadow", "enforce")

BLOCK_MESSAGES = {
    "credits_exhausted": "Your workspace is out of credits. Add credits to continue.",
    "luna_daily_limit": "This Luna has reached its daily credit limit.",
    "luna_monthly_limit": "This Luna has reached its monthly credit limit.",
    "hosting_payment_due": "Hosting payment is due for this Luna. Update billing to continue.",
    "sku_unpriced": "This operation is not enabled for platform-managed billing.",
    "exposure_limit": "Too much spending is in flight for this workspace. Retry once current work settles.",
    "billing_temporarily_unavailable": "Billing is temporarily unavailable. Try again shortly.",
}
_RETRYABLE = {"exposure_limit", "billing_temporarily_unavailable"}

_ROOT_ACTION_TYPES = {"chat", "playbook_run", "scheduled_run", "background_run", "forge_job"}

FINALIZE_JOB = "gateway_finalize"


def billing_mode() -> str:
    mode = (get_settings().billing_mode or "off").strip().lower()
    if mode not in MODES:
        log.error("invalid CLOUD_BILLING_MODE %r — billing disabled", mode)
        return "off"
    return mode


def block_response(code: str) -> JSONResponse:
    """Frozen machine-readable 402 block contract."""
    return JSONResponse(
        status_code=402,
        content={
            "error": {
                "type": "billing",
                "code": code,
                "message": BLOCK_MESSAGES[code],
                "retryable": code in _RETRYABLE,
            }
        },
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_header(value: str | None, max_len: int = 120) -> str | None:
    """Tenant correlation headers are untrusted: printable ASCII, bounded."""
    if not value:
        return None
    value = value.strip()
    if not value or len(value) > max_len:
        return None
    if any(not (32 <= ord(c) < 127) for c in value):
        return None
    return value


def canonical_model(catalog: list[dict], provider: str, model: str) -> str:
    """Resolve a catalog alias to its canonical model id."""
    for entry in catalog:
        if entry.get("provider") != provider:
            continue
        if entry.get("model") == model or model in (entry.get("aliases") or []):
            return entry["model"]
    return model


@dataclass
class BillingContext:
    mode: str
    active: bool = False                 # metered billed route in a non-off mode
    block: str | None = None             # block code — request must not go upstream
    would_block: str | None = None       # observe/shadow decision, recorded only
    operation_id: str | None = None
    account_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    service_slug: str | None = None
    sku: str | None = None
    adapter: str | None = None
    provider: str | None = None
    requested_model: str | None = None
    canonical_model: str | None = None
    context: str = "agent"
    tier: str | None = None
    margin_micro: int = 0
    estimated_credits: int = 0
    estimated_dimensions: dict[str, int] = field(default_factory=dict)
    commercial_version_id: uuid.UUID | None = None
    provider_cost_version_id: uuid.UUID | None = None
    hold_id: uuid.UUID | None = None
    call_id: str | None = None
    root_action_id: str | None = None
    root_action_type: str | None = None
    started_at: datetime = field(default_factory=_utcnow)
    body: bytes = b""


async def _hosting_payment_due(db: AsyncSession, agent_id: uuid.UUID) -> bool:
    row = await db.execute(
        select(AgentHostingPeriod.id)
        .where(
            AgentHostingPeriod.agent_id == agent_id,
            AgentHostingPeriod.state == "payment_due",
        )
        .limit(1)
    )
    return row.scalar_one_or_none() is not None


async def _record_would_block(ctx: BillingContext, db: AsyncSession) -> None:
    """Observe/shadow record of a decision that enforce would have blocked on,
    for routes we cannot meter (no adapter / no tier). One event, no charge."""
    db.add(
        BillableEvent(
            source_idempotency_key=f"{ctx.operation_id}:0",
            call_id=ctx.call_id or ctx.operation_id,
            account_id=ctx.account_id,
            agent_id=ctx.agent_id,
            root_action_id=ctx.root_action_id,
            root_action_type=ctx.root_action_type,
            service=ctx.service_slug,
            sku=ctx.sku or "unpriced",
            context=ctx.context,
            model_tier=ctx.tier,
            provider=ctx.provider,
            model=ctx.canonical_model or ctx.requested_model,
            quantity_json={"would_block": ctx.would_block},
            vendor_cost_micro_usd=0,
            cost_source="estimated",
            status="would_block",
            event_at=ctx.started_at,
        )
    )
    await db.commit()


async def prepare(
    db: AsyncSession,
    *,
    request,
    service_slug: str,
    method: str,
    path: str,
    body: bytes,
    body_json: dict | None,
    agent_id: uuid.UUID,
    catalog: list[dict] | None,
) -> BillingContext:
    """Pre-upstream billing decision for a managed request. Never raises for
    billing reasons — failures map to mode-appropriate decisions.

    The effective mode is per account (039/010): max of the global mode and
    the account's enforcement override. The override map is TTL-cached, so a
    fully-off deployment with no overrides stays a zero-query fast path."""
    mode = billing_mode()
    ctx = BillingContext(mode=mode, agent_id=agent_id, service_slug=service_slug, body=body)
    try:
        overrides = await modes.override_map(db)
    except Exception:  # noqa: BLE001 — billing store down; global mode decides
        log.exception("override map load failed — falling back to global mode")
        overrides = {}
    if mode == "off" and not overrides:
        return ctx

    ctx.operation_id = f"gw:{uuid.uuid4().hex}"
    headers = request.headers
    ctx.context = "direct" if headers.get("x-luna-context") == "direct" else "agent"
    tenant_call_id = _clean_header(headers.get("x-luna-call-id"))
    # Namespaced by the authenticated agent — tenant-supplied ids are
    # correlation metadata only and can never dedupe or skip a charge.
    ctx.call_id = f"{agent_id}:{tenant_call_id}" if tenant_call_id else ctx.operation_id
    ctx.root_action_id = _clean_header(headers.get("x-luna-root-action-id"))
    action_type = _clean_header(headers.get("x-luna-root-action-type"))
    ctx.root_action_type = action_type if action_type in _ROOT_ACTION_TYPES else None

    try:
        agent = await db.get(Agent, agent_id)
        if agent is None:  # token outlived the agent row — treat as no identity
            ctx.block = "billing_temporarily_unavailable" if mode == "enforce" else None
            return ctx
        ctx.account_id = agent.account_id
        mode = modes.combine(mode, overrides.get(agent.account_id))
        ctx.mode = mode
        if mode == "off":
            return ctx
        await ledger.ensure_billing_account(db, agent.account_id)

        route = route_catalog.classify(service_slug, method, path)
        if route is not None and route.kind == "free":
            return ctx

        # Version + tariff snapshots at call start (assignment chain, never
        # the cached pointer).
        ctx.commercial_version_id, config = await rating.resolve_commercial_version(
            db, agent.account_id, ctx.started_at
        )
        ctx.provider_cost_version_id = await rating.resolve_provider_cost_version(
            db, ctx.started_at
        )
        rates = await rating.load_provider_rates(db, ctx.provider_cost_version_id)

        unpriced_reason = None
        if route is None:
            unpriced_reason = "unknown_route"
        else:
            ctx.adapter = route.adapter
            ctx.provider = usage_adapters.provider_for_adapter(route.adapter)
            ctx.sku = route.sku
            if not rating.sku_enabled(config, route.sku):
                unpriced_reason = "sku_disabled"
            else:
                model = usage_adapters.extract_model(
                    route.adapter, body_json, path,
                    headers.get("content-type", ""), body,
                )
                ctx.requested_model = model
                ctx.canonical_model = (
                    canonical_model(catalog or [], ctx.provider, model) if model else None
                )
                ctx.tier = rating.model_tier(config, ctx.canonical_model)
                if ctx.tier is None:
                    unpriced_reason = "model_uncovered"

        if unpriced_reason is not None:
            if mode == "enforce":
                ctx.block = "sku_unpriced"
            else:
                ctx.would_block = "sku_unpriced"
                await _record_would_block(ctx, db)
            return ctx

        if await _hosting_payment_due(db, agent_id):
            if mode == "enforce":
                ctx.block = "hosting_payment_due"
                return ctx
            ctx.would_block = "hosting_payment_due"

        ctx.margin_micro = rating.margin_micro_usd(config, ctx.context, ctx.tier)
        ctx.estimated_dimensions = usage_adapters.estimate_dimensions(
            ctx.adapter, body_json, len(body)
        )
        ctx.estimated_credits = rating.estimate_credits(
            rates,
            provider=ctx.provider,
            model=ctx.canonical_model,
            dimensions=ctx.estimated_dimensions,
            margin_micro=ctx.margin_micro,
        )
        ctx.body = usage_adapters.prepare_managed_body(ctx.adapter, body_json, body)
        ctx.active = True

        if mode == "enforce":
            hold = await ledger.authorize(
                db,
                operation_id=ctx.operation_id,
                account_id=ctx.account_id,
                estimated_credits=ctx.estimated_credits,
                agent_id=agent_id,
                root_action_id=ctx.root_action_id,
                service=service_slug,
                sku=ctx.sku,
                commercial_pricing_version_id=ctx.commercial_version_id,
                provider_cost_version_id=ctx.provider_cost_version_id,
                now=ctx.started_at,
            )
            ctx.hold_id = hold.id
            await db.commit()
        elif mode == "shadow":
            # Real decision, zero customer effect: run authorize inside a
            # savepoint and roll it back.
            nested = await db.begin_nested()
            try:
                await ledger.authorize(
                    db,
                    operation_id=ctx.operation_id,
                    account_id=ctx.account_id,
                    estimated_credits=ctx.estimated_credits,
                    agent_id=agent_id,
                    service=service_slug,
                    sku=ctx.sku,
                    now=ctx.started_at,
                )
            except (ledger.InsufficientBalance, ledger.LimitExceeded) as exc:
                ctx.would_block = ctx.would_block or exc.code
            finally:
                await nested.rollback()
    except (ledger.InsufficientBalance, ledger.LimitExceeded) as exc:
        await db.rollback()
        ctx.block = exc.code
        ctx.active = False
    except Exception:  # noqa: BLE001 — billing store failure
        log.exception(
            "billing prepare failed (mode=%s service=%s op=%s)",
            mode, service_slug, ctx.operation_id,
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        ctx.active = False
        # Fail closed only in enforce mode.
        ctx.block = "billing_temporarily_unavailable" if mode == "enforce" else None
    return ctx


async def finalize(ctx: BillingContext, attempts: list[AttemptFacts], status_code: int) -> None:
    """Post-response persistence: billable events per attempt, the rated
    charge, and the durable settle/release job — one commit. Process death
    before this commit leaves the hold to the stale-hold reaper
    (`needs_reconciliation`), never a silent release."""
    if not ctx.active:
        return
    try:
        async with db_session.get_session() as db:
            rates = await rating.load_provider_rates(db, ctx.provider_cost_version_id)

            usage_missing = status_code < 400 and not any(
                a.billable and a.dimensions for a in attempts
            )
            if usage_missing:
                # Accepted provider work with no parseable usage: record the
                # facts as estimated and leave the hold open for the reaper —
                # never silently settle or release provider spend.
                for attempt in attempts:
                    attempt.cost_source = "estimated"
                    attempt.dimensions = attempt.dimensions or dict(ctx.estimated_dimensions)

            result = rating.rate_call(rates, margin_micro=ctx.margin_micro, attempts=attempts)

            for attempt, attempt_cost in zip(attempts, result.attempt_costs_micro_usd):
                db.add(
                    BillableEvent(
                        source_idempotency_key=f"{ctx.operation_id}:{attempt.attempt_number}",
                        call_id=ctx.call_id or ctx.operation_id,
                        account_id=ctx.account_id,
                        agent_id=ctx.agent_id,
                        root_action_id=ctx.root_action_id,
                        root_action_type=ctx.root_action_type,
                        service=ctx.service_slug,
                        sku=ctx.sku,
                        context=ctx.context,
                        model_tier=ctx.tier,
                        provider=ctx.provider,
                        model=attempt.model or ctx.canonical_model,
                        provider_request_id=attempt.provider_request_id,
                        provider_response_id=attempt.provider_response_id,
                        attempt_number=attempt.attempt_number,
                        quantity_json=attempt.dimensions,
                        vendor_cost_micro_usd=attempt_cost,
                        cost_source=attempt.cost_source,
                        status="recorded",
                        event_at=ctx.started_at,
                    )
                )

            charge_status = {
                "observe": "observed",
                "shadow": "shadow",
                "enforce": "needs_reconciliation" if usage_missing else "pending",
            }[ctx.mode]
            any_billable = any(a.billable for a in attempts)
            db.add(
                RatedCharge(
                    logical_call_id=ctx.operation_id,
                    account_id=ctx.account_id,
                    hold_id=ctx.hold_id,
                    commercial_pricing_version_id=ctx.commercial_version_id,
                    provider_cost_version_id=ctx.provider_cost_version_id,
                    rule_snapshot={
                        "context": ctx.context,
                        "tier": ctx.tier,
                        "sku": ctx.sku,
                        "margin_micro_usd": ctx.margin_micro,
                        "requested_model": ctx.requested_model,
                        "canonical_model": ctx.canonical_model,
                        "estimated_credits": ctx.estimated_credits,
                        "status_code": status_code,
                        "usage_missing": usage_missing,
                        "would_block": ctx.would_block,
                        "unrated_dimensions": result.unrated_dimensions,
                    },
                    vendor_cost_micro_usd=result.vendor_micro_usd if any_billable else 0,
                    margin_micro_usd=result.margin_micro_usd if any_billable else 0,
                    rounding_micro_usd=result.rounding_micro_usd if any_billable else 0,
                    credits=result.credits if any_billable else 0,
                    luna_absorbed_micro_usd=result.luna_absorbed_micro_usd,
                    charge_status=charge_status,
                )
            )

            if ctx.mode == "enforce" and not usage_missing:
                final_credits = result.credits if any_billable else 0
                await billing_worker.enqueue(
                    db,
                    job_type=FINALIZE_JOB,
                    payload={
                        "operation_id": ctx.operation_id,
                        "action": "settle" if final_credits > 0 else "release",
                        "final_credits": final_credits,
                    },
                    dedupe_key=f"gwfin:{ctx.operation_id}",
                )
            await db.commit()
    except Exception:  # noqa: BLE001 — the reaper is the durable backstop
        log.exception(
            "billing finalize failed (mode=%s op=%s) — hold left for the reaper",
            ctx.mode, ctx.operation_id,
        )


async def _handle_gateway_finalize(session: AsyncSession, job) -> dict:
    """Durable settle/release of a gateway hold. Idempotent: ledger.settle
    and ledger.release both replay cleanly, and a hold that went
    needs_reconciliation (disconnect, stale) can still be settled with its
    rated amount."""
    payload = job.payload or {}
    operation_id = payload["operation_id"]
    action = payload["action"]
    if action == "settle":
        txn = await ledger.settle(
            session,
            operation_id=operation_id,
            final_credits=int(payload["final_credits"]),
            reason="gateway usage settlement",
            actor="gateway",
        )
        charge = (
            await session.execute(
                select(RatedCharge).where(RatedCharge.logical_call_id == operation_id)
            )
        ).scalar_one_or_none()
        if charge is not None:
            charge.charge_status = "settled"
            charge.ledger_transaction_id = txn.id
    else:
        await ledger.release(session, operation_id=operation_id)
        charge = (
            await session.execute(
                select(RatedCharge).where(RatedCharge.logical_call_id == operation_id)
            )
        ).scalar_one_or_none()
        if charge is not None:
            charge.charge_status = "released"
    await session.flush()
    return {"operation_id": operation_id, "action": action}


billing_worker.register_handler(FINALIZE_JOB, _handle_gateway_finalize)


async def reap_stale_holds_once(session: AsyncSession) -> int:
    """One reaper pass: expired open holds → needs_reconciliation (never
    silently settled or released)."""
    stale = await ledger.mark_stale_holds(session)
    for hold in stale:
        log.warning(
            "gateway hold %s went stale → needs_reconciliation (account=%s)",
            hold.operation_id, hold.account_id,
        )
    await session.commit()
    return len(stale)


async def stale_hold_reaper_loop(session_factory, *, interval_seconds: float = 60.0):
    import asyncio

    while True:
        try:
            async with session_factory() as session:
                await reap_stale_holds_once(session)
                from cloud.billing.operations import heartbeat as ops_heartbeat
                await ops_heartbeat(session, "hold_reaper", None)
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("stale-hold reaper tick failed")
        await asyncio.sleep(interval_seconds)
