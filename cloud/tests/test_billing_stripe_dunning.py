"""039/007 — dunning: failed renewals grant nothing and mark past_due;
a later verified payment grants once and clears the state; top-ups keep
working while past due (no grace credits either way)."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from cloud.billing import ledger, worker
from cloud.billing.models import (
    BillingJob,
    CreditGrant,
    StripePriceBinding,
    StripeSubscription,
)
from cloud.billing.seed import seed_commercial_v1
from cloud.billing.stripe_gateway import StripeGateway
from cloud.billing.stripe_webhooks import (
    grant_from_paid_invoice,
    grant_from_topup_checkout,
    intake_event,
    mark_invoice_failed,
)

pytestmark = pytest.mark.asyncio

CUS = "cus_test1"
PERIOD_START = datetime(2026, 7, 1, tzinfo=timezone.utc)
PERIOD_END = datetime(2026, 8, 1, tzinfo=timezone.utc)
RETRY_AT = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)


def _unix(dt: datetime) -> int:
    return int(dt.timestamp())


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


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


def _failed_invoice(inv_id="in_fail1", *, pi="pi_fail1", retry=RETRY_AT) -> dict:
    return {
        "id": inv_id, "object": "invoice", "livemode": False,
        "status": "open", "paid_out_of_band": False,
        "payment_intent": pi, "charge": None,
        "currency": "usd", "amount_paid": 0, "tax": 0,
        "customer": CUS, "subscription": "sub_test1",
        "next_payment_attempt": _unix(retry) if retry else None,
        "lines": {"data": [{
            "amount": 9_900, "price": {"id": "price_recurring_99"},
            "period": {"start": _unix(PERIOD_START), "end": _unix(PERIOD_END)},
        }]},
    }


def _paid_invoice(inv_id="in_recover1") -> dict:
    return {
        "id": inv_id, "object": "invoice", "livemode": False,
        "status": "paid", "paid_out_of_band": False,
        "payment_intent": "pi_ok1", "charge": "ch_ok1",
        "currency": "usd", "amount_paid": 9_900, "tax": 0,
        "customer": CUS, "subscription": "sub_test1",
        "lines": {"data": [{
            "amount": 9_900, "price": {"id": "price_recurring_99"},
            "period": {"start": _unix(PERIOD_START), "end": _unix(PERIOD_END)},
        }]},
    }


def _sub(status="past_due") -> dict:
    return {
        "id": "sub_test1", "object": "subscription", "livemode": False,
        "status": status, "customer": CUS,
        "items": {"data": [{"price": {"id": "price_recurring_99"}}]},
        "current_period_start": _unix(PERIOD_START),
        "current_period_end": _unix(PERIOD_END),
        "cancel_at_period_end": False,
    }


async def _setup(db, account) -> FakeStripe:
    version = await seed_commercial_v1(db)
    for p in version.config_json["products"]:
        db.add(StripePriceBinding(
            livemode=False, product_key=p["key"],
            stripe_product_id=f"prod_{p['key']}", stripe_price_id=f"price_{p['key']}",
            price_usd_cents=p["price_usd_cents"], interval=p.get("interval"),
        ))
    ba = await ledger.ensure_billing_account(db, account.id)
    ba.stripe_customer_id = CUS
    await db.commit()
    return FakeStripe()


async def _fail_renewal(db, fake: FakeStripe, *, pi_status="requires_payment_method") -> dict:
    fake.objects["/v1/invoices/in_fail1"] = _failed_invoice()
    fake.objects["/v1/payment_intents/pi_fail1"] = {
        "id": "pi_fail1", "object": "payment_intent", "livemode": False,
        "status": pi_status, "currency": "usd",
    }
    fake.objects["/v1/subscriptions/sub_test1"] = _sub("past_due")
    gw = fake.gateway()
    result = await mark_invoice_failed(db, gw, "evt_fail", "in_fail1")
    await gw.aclose()
    await db.commit()
    return result


async def test_failed_renewal_marks_past_due_and_grants_nothing(db_session, account):
    fake = await _setup(db_session, account)
    result = await _fail_renewal(db_session, fake)
    assert result == {"granted": False, "billing_status": "past_due",
                      "payment_action_required": True}

    ba = await ledger.ensure_billing_account(db_session, account.id)
    assert ba.billing_status == "past_due"
    mirror = (await db_session.execute(select(StripeSubscription))).scalar_one()
    assert mirror.status == "past_due"
    assert mirror.payment_action_required is True
    assert _aware(mirror.next_payment_retry_at) == RETRY_AT
    grants = list((await db_session.execute(select(CreditGrant))).scalars().all())
    assert grants == []


async def test_sca_challenge_maps_to_action_required(db_session, account):
    fake = await _setup(db_session, account)
    result = await _fail_renewal(db_session, fake, pi_status="requires_action")
    assert result["payment_action_required"] is True

    # A PI still mid-processing is not a customer-action state.
    fake.objects["/v1/payment_intents/pi_fail1"]["status"] = "processing"
    gw = fake.gateway()
    result = await mark_invoice_failed(db_session, gw, "evt_fail2", "in_fail1")
    await gw.aclose()
    assert result["payment_action_required"] is False


async def test_later_verified_payment_grants_once_and_recovers(db_session, account):
    fake = await _setup(db_session, account)
    await _fail_renewal(db_session, fake)

    fake.objects["/v1/invoices/in_recover1"] = _paid_invoice()
    fake.objects["/v1/subscriptions/sub_test1"] = _sub("past_due")
    for _ in range(2):  # Smart Retry replay grants exactly once
        gw = fake.gateway()
        result = await grant_from_paid_invoice(db_session, gw, "evt_ok", "in_recover1")
        await gw.aclose()
        await db_session.commit()
        assert result["granted"] is True

    ba = await ledger.ensure_billing_account(db_session, account.id)
    assert ba.billing_status == "active"
    mirror = (await db_session.execute(select(StripeSubscription))).scalar_one()
    assert mirror.payment_action_required is False
    assert mirror.next_payment_retry_at is None
    grants = list((await db_session.execute(select(CreditGrant))).scalars().all())
    assert sum(g.original_credits for g in grants) == 11_000


async def test_topup_while_past_due_grants_but_keeps_dunning_state(db_session, account):
    fake = await _setup(db_session, account)
    await _fail_renewal(db_session, fake)

    fake.objects["/v1/checkout/sessions/cs_topup1"] = {
        "id": "cs_topup1", "object": "checkout.session", "livemode": False,
        "mode": "payment", "payment_status": "paid",
        "payment_intent": "pi_topup1", "customer": CUS,
    }
    fake.objects["/v1/payment_intents/pi_topup1"] = {
        "id": "pi_topup1", "object": "payment_intent", "livemode": False,
        "status": "succeeded", "currency": "usd", "amount_received": 2_500,
        "latest_charge": "ch_topup1",
        "metadata": {"luna_account_id": str(account.id),
                     "luna_product_key": "topup_25",
                     "luna_expected_credits": "2500"},
    }
    gw = fake.gateway()
    result = await grant_from_topup_checkout(db_session, gw, "evt_t", "cs_topup1")
    await gw.aclose()
    await db_session.commit()
    assert result["granted"] is True

    # Credits are spendable, but the dunning notice stays until a verified
    # subscription payment clears it.
    ba = await ledger.ensure_billing_account(db_session, account.id)
    assert ba.billing_status == "past_due"


async def test_failed_invoice_for_unknown_customer_skips(db_session, account):
    fake = await _setup(db_session, account)
    invoice = _failed_invoice()
    invoice["customer"] = "cus_stranger"
    fake.objects["/v1/invoices/in_fail1"] = invoice
    gw = fake.gateway()
    result = await mark_invoice_failed(db_session, gw, "evt_f", "in_fail1")
    await gw.aclose()
    assert result["granted"] is False
    ba = await ledger.ensure_billing_account(db_session, account.id)
    assert ba.billing_status == "active"


async def test_payment_failed_event_flows_through_worker(db_session, account, monkeypatch):
    fake = await _setup(db_session, account)
    fake.objects["/v1/invoices/in_fail1"] = _failed_invoice()
    fake.objects["/v1/payment_intents/pi_fail1"] = {
        "id": "pi_fail1", "object": "payment_intent", "livemode": False,
        "status": "requires_payment_method", "currency": "usd",
    }
    fake.objects["/v1/subscriptions/sub_test1"] = _sub("past_due")
    monkeypatch.setattr("cloud.billing.stripe_webhooks.gateway_factory", fake.gateway)

    event = {"id": "evt_pf1", "type": "invoice.payment_failed", "livemode": False,
             "data": {"object": {"id": "in_fail1", "object": "invoice"}}}
    assert await intake_event(db_session, event) is True
    await db_session.commit()
    assert await worker.run_once(db_session, worker_id="test-worker") == 1

    job = (await db_session.execute(select(BillingJob))).scalar_one()
    assert job.job_type == "stripe.invoice_failed"
    assert job.status == "succeeded"
    ba = await ledger.ensure_billing_account(db_session, account.id)
    assert ba.billing_status == "past_due"
