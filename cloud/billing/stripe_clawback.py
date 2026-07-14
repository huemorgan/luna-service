"""039/007 — refund/dispute clawback against immutable grant lots.

The unit of truth is the StripePayment accumulator row. Refunds and
disputes each set their own cumulative pretax figure from the CANONICAL
Stripe object, then `reconcile_payment_clawback` moves the account to the
implied target:

    effective_pretax = min(pretax, refunded + disputed-if-open-or-lost)
    target_credits   = floor(granted × effective_pretax / pretax)
                       (== granted when fully refunded, so the rounding
                        remainder is reversed too)

Only the delta vs `clawed_credits` is ever applied, so refund + dispute,
replayed events, and refund failures can never double-claw. Application
order: scheduled lots cancel first (no postings — they never posted),
then active remainders reverse from the wallet, and whatever is left was
already consumed and becomes uncovered debt (repaid by future grants).
A won dispute lowers the target and the difference is restored as a new
`refund`-typed lot.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cloud.billing import ledger
from cloud.billing.ledger import CONSUMED, DEBT, WALLET
from cloud.billing.models import CreditConsumption, CreditGrant, StripePayment
from cloud.billing.stripe_gateway import StripeGateway

log = logging.getLogger("billing.stripe")


def _skip(event_id: str, why: str) -> dict:
    log.warning("stripe event %s skipped: %s", event_id, why)
    return {"clawed": 0, "skipped": why}


def _pretax_portion(payment: StripePayment, amount_cents: int) -> int:
    """Pretax share of a refunded/disputed charge amount — tax maps to zero
    credits, and refunding the whole charge means the whole pretax."""
    total = payment.pretax_amount_cents + payment.tax_amount_cents
    if amount_cents <= 0 or total <= 0:
        return 0
    if amount_cents >= total:
        return payment.pretax_amount_cents
    return min(
        payment.pretax_amount_cents,
        amount_cents * payment.pretax_amount_cents // total,
    )


def clawback_target_credits(payment: StripePayment) -> int:
    effective = payment.refunded_pretax_cents
    if payment.dispute_status in ("created", "lost"):
        # `won` releases the disputed portion; `lost` keeps it clawed but a
        # lost dispute never claws a second time on top of its `created`.
        effective += payment.disputed_pretax_cents
    effective = min(effective, payment.pretax_amount_cents)
    if effective >= payment.pretax_amount_cents:
        return payment.granted_credits
    return payment.granted_credits * effective // payment.pretax_amount_cents


def _lot_prefix(payment: StripePayment) -> str:
    # "invoice:{id}" / "pi:{id}" → the compound grant-key prefix used at issue
    # time: stripe:{id}:{product_key}:
    stripe_id = payment.payment_ref.split(":", 1)[1]
    return f"stripe:{stripe_id}:{payment.product_key}:"


async def _payment_lots(db: AsyncSession, payment: StripePayment) -> list[CreditGrant]:
    return list((await db.execute(
        select(CreditGrant)
        .where(
            CreditGrant.account_id == payment.account_id,
            CreditGrant.source_key.like(f"{_lot_prefix(payment)}%"),
        )
        .order_by(CreditGrant.effective_at.desc(), CreditGrant.source_key.desc())
    )).scalars().all())


async def reconcile_payment_clawback(
    db: AsyncSession, payment: StripePayment, *, actor: str = "stripe"
) -> dict:
    """Move the account to the payment's clawback target. Idempotent: the
    delta is computed from committed accumulator state."""
    await ledger.lock_billing_account(db, payment.account_id)
    target = clawback_target_credits(payment)
    delta = target - payment.clawed_credits
    if delta == 0:
        return {"clawed": 0, "restored": 0, "target": target}

    if delta < 0:
        # Dispute won: release the difference as a fresh non-expiring lot;
        # create_grant repays any clawback debt from it automatically.
        restore = -delta
        await ledger.create_grant(
            db,
            account_id=payment.account_id,
            source_type="refund",
            source_key=f"stripe-restore:{payment.payment_ref}:{target}",
            credits=restore,
            visible_category="paid",
            effective_at=ledger._utcnow(),
            expires_at=None,
            stripe_ref=payment.payment_ref,
            actor=actor,
            reason="dispute won — clawback restored",
        )
        payment.clawed_credits = target
        await db.flush()
        return {"clawed": 0, "restored": restore, "target": target}

    left = delta
    # 1) Cancel scheduled lots first (furthest-future first). They never
    #    posted to the wallet, so shrinking them needs no ledger movement —
    #    activation later posts the reduced original.
    for grant in await _payment_lots(db, payment):
        if left <= 0:
            break
        if grant.status != "scheduled" or grant.remaining_credits <= 0:
            continue
        take = min(grant.remaining_credits, left)
        grant.remaining_credits -= take
        grant.original_credits -= take
        if grant.remaining_credits == 0:
            grant.status = "reversed"
        left -= take

    # 2) Reverse active remainders out of the wallet.
    for grant in await _payment_lots(db, payment):
        if left <= 0:
            break
        if grant.status != "active" or grant.remaining_credits <= 0:
            continue
        take = min(grant.remaining_credits, left)
        await ledger.post_transaction(
            db,
            type="reversal",
            idempotency_key=f"clawback:{payment.payment_ref}:{target}:{grant.source_key}",
            request_hash=ledger.canonical_request_hash(
                {"payment": payment.payment_ref, "lot": grant.source_key, "credits": take}
            ),
            account_id=payment.account_id,
            postings=[(WALLET, -take),
                      (f"grant_issuance:{grant.source_type}", take)],
            source_ref=grant.source_key,
            reason="refund/dispute clawback",
            actor=actor,
        )
        grant.remaining_credits -= take
        if grant.remaining_credits == 0:
            grant.status = "reversed" if take == grant.original_credits else "exhausted"
        left -= take

    # 3) Whatever remains was already consumed: reclassify that consumption
    #    as uncovered debt (inverse of a debt repayment; no wallet movement).
    if left > 0:
        txn, created = await ledger.post_transaction(
            db,
            type="reversal",
            idempotency_key=f"clawback-debt:{payment.payment_ref}:{target}",
            request_hash=ledger.canonical_request_hash(
                {"payment": payment.payment_ref, "debt": left}
            ),
            account_id=payment.account_id,
            postings=[(DEBT, left), (CONSUMED, -left)],
            source_ref=payment.payment_ref,
            reason="refund clawback of already-consumed credits",
            actor=actor,
        )
        if created:
            db.add(CreditConsumption(
                charge_transaction_id=txn.id,
                account_id=payment.account_id,
                grant_id=None,
                credits=left,
            ))

    payment.clawed_credits = target
    await db.flush()
    await ledger.rebuild_projection(db, payment.account_id)
    return {"clawed": delta, "restored": 0, "target": target}


# ── Handlers (canonical retrieve → accumulate → reconcile) ───────────────────

async def _payment_for_charge(
    db: AsyncSession, charge: dict
) -> StripePayment | None:
    refs = [f"invoice:{charge.get('invoice')}", f"pi:{charge.get('payment_intent')}"]
    row = (await db.execute(
        select(StripePayment).where(StripePayment.stripe_charge_id == charge.get("id"))
    )).scalar_one_or_none()
    if row is not None:
        return row
    return (await db.execute(
        select(StripePayment).where(StripePayment.payment_ref.in_(refs))
    )).scalar_one_or_none()


async def handle_charge_refunded(
    db: AsyncSession, gw: StripeGateway, event_id: str, charge_id: str
) -> dict:
    charge = await gw.get(f"/v1/charges/{charge_id}")
    if charge.get("currency") != "usd":
        return _skip(event_id, f"currency {charge.get('currency')!r}")
    payment = await _payment_for_charge(db, charge)
    if payment is None:
        return _skip(event_id, f"no recorded payment for charge {charge_id!r}")
    # Canonical cumulative figure — a later refund failure lowers it and the
    # reconcile below restores the difference.
    payment.refunded_pretax_cents = _pretax_portion(
        payment, charge.get("amount_refunded") or 0
    )
    result = await reconcile_payment_clawback(db, payment)
    return {"granted": False, **result}


async def handle_dispute(
    db: AsyncSession, gw: StripeGateway, event_id: str, dispute_id: str
) -> dict:
    dispute = await gw.get(f"/v1/disputes/{dispute_id}")
    if dispute.get("currency") != "usd":
        return _skip(event_id, f"currency {dispute.get('currency')!r}")
    charge_id = dispute.get("charge")
    payment = await _payment_for_charge(db, {"id": charge_id})
    if payment is None:
        return _skip(event_id, f"no recorded payment for charge {charge_id!r}")

    status = dispute.get("status") or ""
    if status == "won":
        payment.dispute_status = "won"
    elif status == "lost":
        payment.dispute_status = "lost"
        payment.disputed_pretax_cents = _pretax_portion(payment, dispute.get("amount") or 0)
    else:  # needs_response / under_review / warning_* — money is on hold
        payment.dispute_status = "created"
        payment.disputed_pretax_cents = _pretax_portion(payment, dispute.get("amount") or 0)
    result = await reconcile_payment_clawback(db, payment)
    return {"granted": False, "dispute_status": payment.dispute_status, **result}
