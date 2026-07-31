"""039/007 — refund/dispute proportional clawback.

Every scenario issues real lots through the invoice/top-up grant path,
then drives the canonical charge/dispute handlers. Assertions check the
StripePayment accumulator, lot states, and the rebuilt balance
projection. Double-claw protection is asserted by replaying handlers."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from cloud.billing import ledger, worker
from cloud.billing.models import (
    AccountBalanceProjection,
    BillingJob,
    CreditGrant,
    StripePayment,
    StripePriceBinding,
)
from cloud.billing.seed import seed_commercial_v1
from cloud.billing.stripe_clawback import (
    clawback_target_credits,
    handle_charge_refunded,
    handle_dispute,
)
from cloud.billing.stripe_gateway import StripeGateway
from cloud.billing.stripe_webhooks import grant_from_paid_invoice, intake_event

pytestmark = pytest.mark.asyncio

CUS = "cus_test1"
PERIOD_START = datetime(2026, 7, 1, tzinfo=timezone.utc)
PERIOD_END = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _unix(dt: datetime) -> int:
    return int(dt.timestamp())


class FakeStripe:
    def __init__(self):
        self.objects: dict[str, dict] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        obj = self.objects.get(request.url.path)
        if obj is None:
            return httpx.Response(404, json={"error": {"message": "no such object"}})
        return httpx.Response(200, json=obj)

    def gateway(self) -> StripeGateway:
        return StripeGateway("sk_test_abc", False,
                             transport=httpx.MockTransport(self.handler))


def _invoice(inv_id="in_test1", *, amount=9_900, price_id="price_recurring_99",
             start=PERIOD_START, end=PERIOD_END) -> dict:
    return {
        "id": inv_id, "object": "invoice", "livemode": False,
        "status": "paid", "paid_out_of_band": False,
        "payment_intent": "pi_inv1", "charge": "ch_inv1",
        "currency": "usd", "amount_paid": amount, "tax": 0,
        "customer": CUS, "subscription": "sub_test1",
        "lines": {"data": [{
            "amount": amount, "price": {"id": price_id},
            "period": {"start": _unix(start), "end": _unix(end)},
        }]},
    }


def _sub(price_id="price_recurring_99", start=PERIOD_START, end=PERIOD_END) -> dict:
    return {
        "id": "sub_test1", "object": "subscription", "livemode": False,
        "status": "active", "customer": CUS,
        "items": {"data": [{"price": {"id": price_id}}]},
        "current_period_start": _unix(start), "current_period_end": _unix(end),
        "cancel_at_period_end": False,
    }


def _charge(charge_id="ch_inv1", *, amount=9_900, refunded=0, currency="usd",
            invoice="in_test1", pi="pi_inv1") -> dict:
    return {"id": charge_id, "object": "charge", "livemode": False,
            "currency": currency, "amount": amount, "amount_refunded": refunded,
            "invoice": invoice, "payment_intent": pi}


def _dispute(dispute_id="dp_1", *, charge="ch_inv1", amount=9_900,
             status="needs_response", currency="usd") -> dict:
    return {"id": dispute_id, "object": "dispute", "livemode": False,
            "charge": charge, "amount": amount, "status": status,
            "currency": currency}


async def _seed_bound_catalog(db) -> dict:
    version = await seed_commercial_v1(db)
    config = version.config_json
    for p in config["products"]:
        db.add(StripePriceBinding(
            livemode=False, product_key=p["key"],
            stripe_product_id=f"prod_{p['key']}", stripe_price_id=f"price_{p['key']}",
            price_usd_cents=p["price_usd_cents"], interval=p.get("interval"),
        ))
    await db.commit()
    return config


async def _paid_monthly_invoice(db, account, fake: FakeStripe) -> StripePayment:
    """Issue the recurring_99 monthly grant (9,900 paid + 1,100 bonus)."""
    await _seed_bound_catalog(db)
    ba = await ledger.ensure_billing_account(db, account.id)
    ba.stripe_customer_id = CUS
    fake.objects["/v1/invoices/in_test1"] = _invoice()
    fake.objects["/v1/subscriptions/sub_test1"] = _sub()
    gw = fake.gateway()
    result = await grant_from_paid_invoice(db, gw, "evt_paid", "in_test1")
    await gw.aclose()
    await db.commit()
    assert result["granted"] is True
    return (await db.execute(select(StripePayment))).scalar_one()


async def _projection(db, account_id) -> AccountBalanceProjection:
    return (await db.execute(
        select(AccountBalanceProjection)
        .where(AccountBalanceProjection.account_id == account_id)
    )).scalar_one()


async def _grants(db, account_id) -> list[CreditGrant]:
    return list((await db.execute(
        select(CreditGrant).where(CreditGrant.account_id == account_id)
        .order_by(CreditGrant.source_key)
    )).scalars().all())


async def _refund(db, fake: FakeStripe, refunded: int, *, amount=9_900) -> dict:
    fake.objects["/v1/charges/ch_inv1"] = _charge(amount=amount, refunded=refunded)
    gw = fake.gateway()
    result = await handle_charge_refunded(db, gw, "evt_refund", "ch_inv1")
    await gw.aclose()
    await db.commit()
    return result


async def _dispute_event(db, fake: FakeStripe, status: str, *, amount=9_900) -> dict:
    fake.objects["/v1/disputes/dp_1"] = _dispute(amount=amount, status=status)
    gw = fake.gateway()
    result = await handle_dispute(db, gw, "evt_dispute", "dp_1")
    await gw.aclose()
    await db.commit()
    return result


# ── Refunds ──────────────────────────────────────────────────────────────────

async def test_full_refund_of_unspent_payment_reverses_everything(db_session, account):
    fake = FakeStripe()
    payment = await _paid_monthly_invoice(db_session, account, fake)

    result = await _refund(db_session, fake, 9_900)
    assert result["clawed"] == 11_000
    assert result["target"] == 11_000

    for g in await _grants(db_session, account.id):
        assert g.remaining_credits == 0
        assert g.status == "reversed"
    proj = await _projection(db_session, account.id)
    assert proj.posted_balance_credits == 0
    assert proj.debt_credits == 0
    await db_session.refresh(payment)
    assert payment.refunded_pretax_cents == 9_900
    assert payment.clawed_credits == 11_000

    # Replayed refund event claws nothing more.
    replay = await _refund(db_session, fake, 9_900)
    assert replay["clawed"] == 0


async def test_partial_refund_claws_proportionally(db_session, account):
    fake = FakeStripe()
    await _paid_monthly_invoice(db_session, account, fake)

    result = await _refund(db_session, fake, 4_950)  # 50%
    assert result["target"] == 5_500  # floor(11_000 × 4_950 / 9_900)
    proj = await _projection(db_session, account.id)
    assert proj.posted_balance_credits == 5_500

    # Second partial refund tops the cumulative figure up to 100%.
    result = await _refund(db_session, fake, 9_900)
    assert result["target"] == 11_000
    assert result["clawed"] == 5_500
    proj = await _projection(db_session, account.id)
    assert proj.posted_balance_credits == 0


async def test_refund_of_spent_credits_creates_debt_repaid_by_next_grant(db_session, account):
    fake = FakeStripe()
    await _paid_monthly_invoice(db_session, account, fake)
    await ledger.charge(
        db_session, account_id=account.id, idempotency_key="charge-1",
        credits=10_000, actor="test",
    )
    await db_session.commit()

    result = await _refund(db_session, fake, 9_900)
    assert result["clawed"] == 11_000
    proj = await _projection(db_session, account.id)
    assert proj.posted_balance_credits == 0
    assert proj.debt_credits == 10_000  # 1,000 unspent reversed; the rest is owed

    # A later grant repays the clawback debt before becoming spendable.
    await ledger.create_grant(
        db_session, account_id=account.id, source_type="topup",
        source_key="stripe:pi_new:topup_100:paid:0", credits=10_000,
        visible_category="topup", effective_at=ledger._utcnow(), expires_at=None,
        cash_paid_micro_usd=100_000_000, actor="stripe",
    )
    await db_session.commit()
    proj = await _projection(db_session, account.id)
    assert proj.debt_credits == 0
    assert proj.posted_balance_credits == 10_000  # wallet movement posts; debt eats the lot


async def test_yearly_refund_cancels_scheduled_lots_first(db_session, account):
    fake = FakeStripe()
    await _seed_bound_catalog(db_session)
    ba = await ledger.ensure_billing_account(db_session, account.id)
    ba.stripe_customer_id = CUS
    # Anchor to now: with a fixed past start, monthly lots post as real time
    # advances and the refund no longer fits inside the scheduled remainder.
    start = datetime.now(timezone.utc) - timedelta(days=1)
    end = start + timedelta(days=365)
    fake.objects["/v1/invoices/in_year1"] = _invoice(
        "in_year1", amount=118_800, price_id="price_recurring_99_yearly",
        start=start, end=end)
    fake.objects["/v1/subscriptions/sub_test1"] = _sub(
        price_id="price_recurring_99_yearly", start=start, end=end)
    gw = fake.gateway()
    assert (await grant_from_paid_invoice(db_session, gw, "evt_y", "in_year1"))["granted"]
    await gw.aclose()
    await db_session.commit()

    grants = await _grants(db_session, account.id)
    scheduled_before = sum(g.remaining_credits for g in grants if g.status == "scheduled")
    proj_before = await _projection(db_session, account.id)
    assert scheduled_before > 0

    # A 40% refund fits entirely inside the scheduled (never-posted) lots:
    # the active wallet balance must not move.
    fake.objects["/v1/charges/ch_inv1"] = _charge(
        amount=118_800, refunded=47_520, invoice="in_year1")
    gw = fake.gateway()
    result = await handle_charge_refunded(db_session, gw, "evt_r", "ch_inv1")
    await gw.aclose()
    await db_session.commit()

    target = 151_800 * 47_520 // 118_800
    assert result["target"] == target
    grants = await _grants(db_session, account.id)
    scheduled_after = sum(g.remaining_credits for g in grants if g.status in ("scheduled", "reversed"))
    assert scheduled_before - scheduled_after == target
    proj_after = await _projection(db_session, account.id)
    assert proj_after.posted_balance_credits == proj_before.posted_balance_credits


# ── Disputes ─────────────────────────────────────────────────────────────────

async def test_dispute_created_claws_once_and_lost_never_double_claws(db_session, account):
    fake = FakeStripe()
    payment = await _paid_monthly_invoice(db_session, account, fake)

    created = await _dispute_event(db_session, fake, "needs_response")
    assert created["clawed"] == 11_000
    assert (await _projection(db_session, account.id)).posted_balance_credits == 0

    lost = await _dispute_event(db_session, fake, "lost")
    assert lost["clawed"] == 0  # no second reversal
    await db_session.refresh(payment)
    assert payment.dispute_status == "lost"
    assert payment.clawed_credits == 11_000


async def test_dispute_won_restores_via_new_postings(db_session, account):
    fake = FakeStripe()
    payment = await _paid_monthly_invoice(db_session, account, fake)
    await _dispute_event(db_session, fake, "under_review")
    assert (await _projection(db_session, account.id)).posted_balance_credits == 0

    won = await _dispute_event(db_session, fake, "won")
    assert won["restored"] == 11_000
    proj = await _projection(db_session, account.id)
    assert proj.posted_balance_credits == 11_000
    await db_session.refresh(payment)
    assert payment.dispute_status == "won"
    assert payment.clawed_credits == 0
    restore = next(g for g in await _grants(db_session, account.id)
                   if g.source_key.startswith("stripe-restore:"))
    assert restore.source_type == "refund"
    assert restore.remaining_credits == 11_000
    assert restore.expires_at is None


async def test_refund_plus_dispute_never_double_claws(db_session, account):
    fake = FakeStripe()
    payment = await _paid_monthly_invoice(db_session, account, fake)
    await _refund(db_session, fake, 9_900)
    result = await _dispute_event(db_session, fake, "needs_response")
    assert result["clawed"] == 0  # effective pretax caps at the payment amount
    await db_session.refresh(payment)
    assert payment.clawed_credits == 11_000


async def test_foreign_or_wrong_currency_charges_claw_nothing(db_session, account):
    fake = FakeStripe()
    await _paid_monthly_invoice(db_session, account, fake)
    fake.objects["/v1/charges/ch_other"] = _charge(
        "ch_other", refunded=9_900, invoice="in_unknown", pi="pi_unknown")
    fake.objects["/v1/charges/ch_eur"] = _charge(refunded=9_900, currency="eur")
    gw = fake.gateway()
    for cid in ("ch_other", "ch_eur"):
        result = await handle_charge_refunded(db_session, gw, "evt_x", cid)
        assert result["clawed"] == 0
    await gw.aclose()
    assert (await _projection(db_session, account.id)).posted_balance_credits == 11_000


# ── Intake routing + worker end-to-end ───────────────────────────────────────

async def test_refund_event_flows_through_worker(db_session, account, monkeypatch):
    fake = FakeStripe()
    await _paid_monthly_invoice(db_session, account, fake)
    fake.objects["/v1/charges/ch_inv1"] = _charge(refunded=9_900)
    monkeypatch.setattr("cloud.billing.stripe_webhooks.gateway_factory", fake.gateway)

    event = {"id": "evt_ref1", "type": "charge.refunded", "livemode": False,
             "data": {"object": {"id": "ch_inv1", "object": "charge"}}}
    assert await intake_event(db_session, event) is True
    await db_session.commit()
    assert await worker.run_once(db_session, worker_id="test-worker") == 1

    job = (await db_session.execute(select(BillingJob))).scalar_one()
    assert job.job_type == "stripe.charge_refunded"
    assert job.status == "succeeded"
    assert (await _projection(db_session, account.id)).posted_balance_credits == 0
