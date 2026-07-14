"""039/007 — webhook intake, signature-authenticated route, and grant
issuance handlers (monthly, yearly 12-lot + gift, top-ups).

Handlers never trust event payloads — every test fakes the CANONICAL
Stripe objects behind httpx.MockTransport and exercises the retrieve →
gate → grant path. Idempotency is asserted by running everything twice."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from cloud.billing import ledger, worker
from cloud.billing.models import (
    BillingJob,
    CreditGrant,
    ProcessedWebhook,
    StripePayment,
    StripePriceBinding,
    StripeSubscription,
)
from cloud.billing.seed import seed_commercial_v1
from cloud.billing.stripe_gateway import StripeGateway
from cloud.billing.stripe_webhooks import (
    add_months_clamped,
    grant_from_paid_invoice,
    grant_from_topup_checkout,
    intake_event,
    sync_subscription,
)
from cloud.config import Settings

pytestmark = pytest.mark.asyncio

WEBHOOK_SECRET = "whsec_abc"
CUS = "cus_test1"

PERIOD_START = datetime(2026, 7, 1, tzinfo=timezone.utc)
PERIOD_END = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _unix(dt: datetime) -> int:
    return int(dt.timestamp())


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; normalize for comparison."""
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _settings(**overrides) -> Settings:
    base = dict(
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        stripe_secret_key="sk_test_abc",
        stripe_publishable_key="pk_test_abc",
        stripe_webhook_secret=WEBHOOK_SECRET,
        stripe_livemode=False,
        base_url="http://localhost:8100",
    )
    return Settings(**{**base, **overrides})


def _sign(body: bytes, secret: str = WEBHOOK_SECRET, ts: int | None = None) -> str:
    ts = ts if ts is not None else int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


class FakeStripe:
    """Canonical-object store served over httpx.MockTransport GETs."""

    def __init__(self):
        self.objects: dict[str, dict] = {}
        self.get_paths: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.get_paths.append(request.url.path)
        obj = self.objects.get(request.url.path)
        if obj is None:
            return httpx.Response(404, json={"error": {"message": "no such object"}})
        return httpx.Response(200, json=obj)

    def gateway(self) -> StripeGateway:
        return StripeGateway("sk_test_abc", False,
                             transport=httpx.MockTransport(self.handler))


def _invoice(inv_id="in_test1", *, amount=9_900, currency="usd", status="paid",
             customer=CUS, sub_id="sub_test1", price_id="price_recurring_99",
             start=PERIOD_START, end=PERIOD_END, lines=None, **overrides) -> dict:
    body = {
        "id": inv_id, "object": "invoice", "livemode": False,
        "status": status, "paid_out_of_band": False,
        "payment_intent": "pi_inv1", "charge": "ch_inv1",
        "currency": currency, "amount_paid": amount, "tax": 0,
        "customer": customer, "subscription": sub_id,
        "lines": {"data": lines if lines is not None else [{
            "amount": amount,
            "price": {"id": price_id},
            "period": {"start": _unix(start), "end": _unix(end)},
        }]},
    }
    body.update(overrides)
    return body


def _subscription(sub_id="sub_test1", *, status="active", customer=CUS,
                  price_id="price_recurring_99", start=PERIOD_START,
                  end=PERIOD_END, **overrides) -> dict:
    body = {
        "id": sub_id, "object": "subscription", "livemode": False,
        "status": status, "customer": customer,
        "items": {"data": [{"price": {"id": price_id}}]},
        "current_period_start": _unix(start),
        "current_period_end": _unix(end),
        "cancel_at_period_end": False,
    }
    body.update(overrides)
    return body


def _event(event_id="evt_1", event_type="invoice.paid", obj=None, livemode=False) -> dict:
    return {"id": event_id, "type": event_type, "livemode": livemode,
            "data": {"object": obj or {"id": "in_test1", "object": "invoice"}}}


async def _seed_bound_catalog(db) -> dict:
    version = await seed_commercial_v1(db)
    config = version.config_json
    for p in config["products"]:
        db.add(StripePriceBinding(
            livemode=False,
            product_key=p["key"],
            stripe_product_id=f"prod_{p['key']}",
            stripe_price_id=f"price_{p['key']}",
            price_usd_cents=p["price_usd_cents"],
            interval=p.get("interval"),
        ))
    await db.commit()
    return config


async def _stripe_billing_account(db, account):
    ba = await ledger.ensure_billing_account(db, account.id)
    ba.stripe_customer_id = CUS
    await db.commit()
    return ba


async def _grants(db, account_id) -> list[CreditGrant]:
    return list((await db.execute(
        select(CreditGrant).where(CreditGrant.account_id == account_id)
        .order_by(CreditGrant.source_key)
    )).scalars().all())


# ── Calendar-month clamping ──────────────────────────────────────────────────

async def test_add_months_clamps_to_short_months():
    jan31 = datetime(2026, 1, 31, tzinfo=timezone.utc)
    assert add_months_clamped(jan31, 1) == datetime(2026, 2, 28, tzinfo=timezone.utc)
    assert add_months_clamped(jan31, 3) == datetime(2026, 4, 30, tzinfo=timezone.utc)
    assert add_months_clamped(jan31, 12) == datetime(2027, 1, 31, tzinfo=timezone.utc)
    jan30 = datetime(2026, 1, 30, tzinfo=timezone.utc)
    assert add_months_clamped(jan30, 1) == datetime(2026, 2, 28, tzinfo=timezone.utc)
    jan29_leap = datetime(2028, 1, 29, tzinfo=timezone.utc)
    assert add_months_clamped(jan29_leap, 1) == datetime(2028, 2, 29, tzinfo=timezone.utc)
    jan31_leap = datetime(2028, 1, 31, tzinfo=timezone.utc)
    assert add_months_clamped(jan31_leap, 1) == datetime(2028, 2, 29, tzinfo=timezone.utc)


# ── Intake (dedupe + enqueue) ────────────────────────────────────────────────

async def test_intake_dedupes_and_enqueues_once(db_session):
    event = _event()
    assert await intake_event(db_session, event) is True
    await db_session.commit()
    assert await intake_event(db_session, event) is False
    jobs = list((await db_session.execute(select(BillingJob))).scalars().all())
    assert len(jobs) == 1
    assert jobs[0].job_type == "stripe.invoice_paid"
    assert jobs[0].payload["object_id"] == "in_test1"
    row = (await db_session.execute(select(ProcessedWebhook))).scalar_one()
    assert row.state == "queued"


async def test_intake_ignores_unhandled_event_types(db_session):
    assert await intake_event(db_session, _event(event_type="product.created")) is True
    await db_session.commit()
    assert (await db_session.execute(select(BillingJob))).scalar_one_or_none() is None
    row = (await db_session.execute(select(ProcessedWebhook))).scalar_one()
    assert row.state == "ignored"


# ── invoice.paid → monthly grant ─────────────────────────────────────────────

async def test_monthly_invoice_grants_paid_and_bonus_once(db_session, account):
    await _seed_bound_catalog(db_session)
    await _stripe_billing_account(db_session, account)
    fake = FakeStripe()
    fake.objects["/v1/invoices/in_test1"] = _invoice()
    fake.objects["/v1/subscriptions/sub_test1"] = _subscription()

    for _ in range(2):  # duplicate delivery grants exactly once
        gw = fake.gateway()
        result = await grant_from_paid_invoice(db_session, gw, "evt_1", "in_test1")
        await gw.aclose()
        await db_session.commit()
        assert result == {"granted": True, "credits": 11_000, "lots": 2,
                          "product": "recurring_99"}

    grants = await _grants(db_session, account.id)
    assert len(grants) == 2
    paid = next(g for g in grants if g.visible_category == "paid")
    bonus = next(g for g in grants if g.visible_category == "bonus")
    assert paid.original_credits == 9_900
    assert paid.cash_paid_micro_usd == 9_900 * 10_000
    assert _aware(paid.expires_at) == PERIOD_END
    assert bonus.original_credits == 1_100
    assert bonus.cash_paid_micro_usd == 0
    assert _aware(bonus.expires_at) == PERIOD_END
    assert paid.source_key == "stripe:in_test1:recurring_99:paid:0"

    payment = (await db_session.execute(select(StripePayment))).scalar_one()
    assert payment.payment_ref == "invoice:in_test1"
    assert payment.kind == "subscription"
    assert payment.pretax_amount_cents == 9_900
    assert payment.granted_credits == 11_000
    assert payment.stripe_charge_id == "ch_inv1"

    mirror = (await db_session.execute(select(StripeSubscription))).scalar_one()
    assert mirror.status == "active"
    assert mirror.product_key == "recurring_99"
    assert mirror.payment_action_required is False


async def test_yearly_invoice_grants_12_paid_plus_bonus_plus_gift(db_session, account):
    await _seed_bound_catalog(db_session)
    await _stripe_billing_account(db_session, account)
    # Jan 31 anchor exercises short-month clamping; the year straddles "now"
    # so early lots are active and late lots scheduled.
    start = datetime(2026, 1, 31, tzinfo=timezone.utc)
    end = datetime(2027, 1, 31, tzinfo=timezone.utc)
    fake = FakeStripe()
    fake.objects["/v1/invoices/in_year1"] = _invoice(
        "in_year1", amount=118_800, price_id="price_recurring_99_yearly",
        start=start, end=end,
    )
    fake.objects["/v1/subscriptions/sub_test1"] = _subscription(
        price_id="price_recurring_99_yearly", start=start, end=end,
    )

    for _ in range(2):
        gw = fake.gateway()
        result = await grant_from_paid_invoice(db_session, gw, "evt_y", "in_year1")
        await gw.aclose()
        await db_session.commit()
        assert result["granted"] is True
        assert result["lots"] == 25  # 12 paid + 12 bonus + 1 gift
        assert result["credits"] == 118_800 + 13_200 + 19_800

    grants = await _grants(db_session, account.id)
    paid = [g for g in grants if g.visible_category == "paid"]
    bonus = [g for g in grants if g.visible_category == "bonus"]
    gift = [g for g in grants if g.visible_category == "gift"]
    assert (len(paid), len(bonus), len(gift)) == (12, 12, 1)
    assert len({g.source_key for g in grants}) == 25

    by_key = {g.source_key: g for g in grants}
    ref = "stripe:in_year1:recurring_99_yearly"
    # Lot 0 starts at period start; lot 1 boundary clamps Jan 31 → Feb 28.
    feb28 = datetime(2026, 2, 28, tzinfo=timezone.utc)
    assert _aware(by_key[f"{ref}:paid:0"].effective_at) == start
    assert _aware(by_key[f"{ref}:paid:0"].expires_at) == feb28
    assert _aware(by_key[f"{ref}:paid:1"].effective_at) == feb28
    # The final lot ends exactly at the Stripe period end.
    assert _aware(by_key[f"{ref}:paid:11"].expires_at) == end
    assert _aware(by_key[f"{ref}:gift:0"].effective_at) == start
    assert _aware(by_key[f"{ref}:gift:0"].expires_at) == end
    assert all(g.original_credits == 9_900 for g in paid)
    assert all(g.original_credits == 1_100 for g in bonus)
    assert gift[0].original_credits == 19_800
    # Future-effective lots are scheduled, not active.
    assert by_key[f"{ref}:paid:0"].status == "active"
    assert by_key[f"{ref}:paid:11"].status == "scheduled"

    payment = (await db_session.execute(select(StripePayment))).scalar_one()
    assert payment.pretax_amount_cents == 118_800
    assert payment.granted_credits == 151_800


@pytest.mark.parametrize("mutate, why", [
    (dict(status="open"), "unpaid"),
    (dict(paid_out_of_band=True), "out of band"),
    (dict(payment_intent=None, charge=None), "no payment source"),
    (dict(currency="eur"), "wrong currency"),
    (dict(amount_paid=0), "zero value"),
    (dict(subscription=None), "not a subscription"),
    (dict(customer="cus_stranger"), "unknown customer"),
    (dict(amount=5_000), "pretax != catalog price"),
])
async def test_bad_invoices_grant_nothing(db_session, account, mutate, why):
    await _seed_bound_catalog(db_session)
    await _stripe_billing_account(db_session, account)
    kwargs = dict(mutate)
    amount = kwargs.pop("amount", 9_900)
    fake = FakeStripe()
    fake.objects["/v1/invoices/in_bad"] = _invoice("in_bad", amount=amount, **kwargs)
    fake.objects["/v1/subscriptions/sub_test1"] = _subscription()
    gw = fake.gateway()
    result = await grant_from_paid_invoice(db_session, gw, "evt_bad", "in_bad")
    await gw.aclose()
    assert result["granted"] is False, why
    assert await _grants(db_session, account.id) == []
    assert (await db_session.execute(select(StripePayment))).scalar_one_or_none() is None


async def test_multiline_invoice_and_unbound_price_grant_nothing(db_session, account):
    await _seed_bound_catalog(db_session)
    await _stripe_billing_account(db_session, account)
    fake = FakeStripe()
    line = {"amount": 9_900, "price": {"id": "price_recurring_99"},
            "period": {"start": _unix(PERIOD_START), "end": _unix(PERIOD_END)}}
    fake.objects["/v1/invoices/in_multi"] = _invoice("in_multi", lines=[line, line])
    fake.objects["/v1/invoices/in_unbound"] = _invoice(
        "in_unbound", price_id="price_not_ours")
    fake.objects["/v1/subscriptions/sub_test1"] = _subscription()
    gw = fake.gateway()
    for inv in ("in_multi", "in_unbound"):
        result = await grant_from_paid_invoice(db_session, gw, "evt_x", inv)
        assert result["granted"] is False
    await gw.aclose()
    assert await _grants(db_session, account.id) == []


async def test_incomplete_subscription_invoice_grants_nothing(db_session, account):
    await _seed_bound_catalog(db_session)
    await _stripe_billing_account(db_session, account)
    fake = FakeStripe()
    fake.objects["/v1/invoices/in_test1"] = _invoice()
    fake.objects["/v1/subscriptions/sub_test1"] = _subscription(status="incomplete")
    gw = fake.gateway()
    result = await grant_from_paid_invoice(db_session, gw, "evt_i", "in_test1")
    await gw.aclose()
    assert result["granted"] is False
    assert await _grants(db_session, account.id) == []


# ── checkout.session.completed → top-up grant ────────────────────────────────

def _topup_objects(fake: FakeStripe, account_id, *, amount=2_500,
                   product_key="topup_25", pi_status="succeeded",
                   metadata_account=None, mode="payment") -> None:
    fake.objects["/v1/checkout/sessions/cs_topup1"] = {
        "id": "cs_topup1", "object": "checkout.session", "livemode": False,
        "mode": mode, "payment_status": "paid",
        "payment_intent": "pi_topup1", "customer": CUS,
    }
    fake.objects["/v1/payment_intents/pi_topup1"] = {
        "id": "pi_topup1", "object": "payment_intent", "livemode": False,
        "status": pi_status, "currency": "usd", "amount_received": amount,
        "latest_charge": "ch_topup1",
        "metadata": {
            "luna_account_id": metadata_account or str(account_id),
            "luna_product_key": product_key,
            "luna_expected_credits": "2500",
        },
    }


async def test_topup_checkout_grants_never_expiring_credits_once(db_session, account):
    await _seed_bound_catalog(db_session)
    await _stripe_billing_account(db_session, account)
    fake = FakeStripe()
    _topup_objects(fake, account.id)

    for _ in range(2):
        gw = fake.gateway()
        result = await grant_from_topup_checkout(db_session, gw, "evt_t", "cs_topup1")
        await gw.aclose()
        await db_session.commit()
        assert result == {"granted": True, "credits": 2_500, "product": "topup_25"}

    grants = await _grants(db_session, account.id)
    assert len(grants) == 1
    assert grants[0].visible_category == "topup"
    assert grants[0].expires_at is None
    assert grants[0].cash_paid_micro_usd == 2_500 * 10_000
    assert grants[0].source_key == "stripe:pi_topup1:topup_25:paid:0"
    payment = (await db_session.execute(select(StripePayment))).scalar_one()
    assert payment.payment_ref == "pi:pi_topup1"
    assert payment.kind == "topup"


@pytest.mark.parametrize("mutate", [
    dict(amount=2_600),                          # charged ≠ catalog price
    dict(metadata_account=str(uuid.uuid4())),    # foreign account in metadata
    dict(pi_status="requires_capture"),          # money not actually captured
    dict(mode="subscription"),                   # sub sessions grant via invoice
    dict(product_key="recurring_99"),            # not a top-up product
])
async def test_bad_topup_sessions_grant_nothing(db_session, account, mutate):
    await _seed_bound_catalog(db_session)
    await _stripe_billing_account(db_session, account)
    fake = FakeStripe()
    _topup_objects(fake, account.id, **mutate)
    gw = fake.gateway()
    result = await grant_from_topup_checkout(db_session, gw, "evt_t", "cs_topup1")
    await gw.aclose()
    assert result["granted"] is False
    assert await _grants(db_session, account.id) == []


# ── subscription lifecycle mirror ────────────────────────────────────────────

async def test_subscription_sync_mirrors_canonical_state(db_session, account):
    await _seed_bound_catalog(db_session)
    await _stripe_billing_account(db_session, account)
    fake = FakeStripe()
    fake.objects["/v1/subscriptions/sub_test1"] = _subscription(status="canceled")
    gw = fake.gateway()
    result = await sync_subscription(db_session, gw, "evt_s", "sub_test1")
    await gw.aclose()
    assert result == {"status": "canceled", "product": "recurring_99"}
    mirror = (await db_session.execute(select(StripeSubscription))).scalar_one()
    assert mirror.status == "canceled"
    assert _aware(mirror.current_period_end) == PERIOD_END


# ── Route: signature is the auth ─────────────────────────────────────────────

async def test_route_503_when_webhook_secret_unset(anon_client):
    resp = await anon_client.post("/api/webhooks/stripe", content=b"{}")
    assert resp.status_code == 503


async def test_route_rejects_bad_signatures(anon_client, monkeypatch):
    monkeypatch.setattr("cloud.api.stripe_webhook_routes.get_settings",
                        lambda: _settings())
    body = json.dumps(_event()).encode()
    for headers in (
        {},                                                        # no header
        {"stripe-signature": "t=1,v1=deadbeef"},                   # wrong mac
        {"stripe-signature": _sign(body, secret="whsec_wrong")},   # wrong secret
        {"stripe-signature": _sign(body, ts=int(time.time()) - 600)},  # stale
    ):
        resp = await anon_client.post("/api/webhooks/stripe", content=body,
                                      headers=headers)
        assert resp.status_code == 400, headers


async def test_route_rejects_livemode_mismatch(anon_client, monkeypatch):
    monkeypatch.setattr("cloud.api.stripe_webhook_routes.get_settings",
                        lambda: _settings())
    body = json.dumps(_event(livemode=True)).encode()
    resp = await anon_client.post(
        "/api/webhooks/stripe", content=body,
        headers={"stripe-signature": _sign(body)})
    assert resp.status_code == 400
    assert "livemode" in resp.json()["detail"]


async def test_route_accepts_and_dedupes_valid_events(anon_client, monkeypatch, db_session):
    monkeypatch.setattr("cloud.api.stripe_webhook_routes.get_settings",
                        lambda: _settings())
    body = json.dumps(_event()).encode()
    headers = {"stripe-signature": _sign(body)}
    first = await anon_client.post("/api/webhooks/stripe", content=body, headers=headers)
    assert first.status_code == 200
    assert first.json() == {"received": True, "duplicate": False}
    second = await anon_client.post("/api/webhooks/stripe", content=body, headers=headers)
    assert second.status_code == 200
    assert second.json() == {"received": True, "duplicate": True}
    jobs = list((await db_session.execute(select(BillingJob))).scalars().all())
    assert len(jobs) == 1


# ── End-to-end: route intake → worker tick → grant ───────────────────────────

async def test_worker_processes_queued_invoice_event(db_session, account, monkeypatch):
    await _seed_bound_catalog(db_session)
    await _stripe_billing_account(db_session, account)
    fake = FakeStripe()
    fake.objects["/v1/invoices/in_test1"] = _invoice()
    fake.objects["/v1/subscriptions/sub_test1"] = _subscription()
    monkeypatch.setattr("cloud.billing.stripe_webhooks.gateway_factory", fake.gateway)

    await intake_event(db_session, _event())
    await db_session.commit()
    done = await worker.run_once(db_session, worker_id="test-worker")
    assert done == 1

    grants = await _grants(db_session, account.id)
    assert sum(g.original_credits for g in grants) == 11_000
    row = (await db_session.execute(select(ProcessedWebhook))).scalar_one()
    assert row.state == "processed"
    assert row.processed_at is not None
    job = (await db_session.execute(select(BillingJob))).scalar_one()
    assert job.status == "succeeded"
    assert job.result["granted"] is True


async def test_worker_retries_when_stripe_errors(db_session, account, monkeypatch):
    await _seed_bound_catalog(db_session)
    await _stripe_billing_account(db_session, account)

    def _broken_gateway():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(500, json={"error": {"message": "boom"}}))
        return StripeGateway("sk_test_abc", False, transport=transport)

    monkeypatch.setattr("cloud.billing.stripe_webhooks.gateway_factory", _broken_gateway)
    await intake_event(db_session, _event())
    await db_session.commit()
    done = await worker.run_once(db_session, worker_id="test-worker")
    assert done == 0

    job = (await db_session.execute(select(BillingJob))).scalar_one()
    assert job.status == "pending"  # retry scheduled, not lost
    assert job.attempts == 1
    assert "boom" in (job.last_error or "")
    assert await _grants(db_session, account.id) == []


async def test_worker_fails_visibly_when_stripe_unconfigured(db_session, account, monkeypatch):
    monkeypatch.setattr("cloud.billing.stripe_webhooks.gateway_factory", lambda: None)
    await intake_event(db_session, _event())
    await db_session.commit()
    done = await worker.run_once(db_session, worker_id="test-worker")
    assert done == 0
    job = (await db_session.execute(select(BillingJob))).scalar_one()
    assert job.status == "pending"
    assert "not configured" in (job.last_error or "")
