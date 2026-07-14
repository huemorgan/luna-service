"""039/007 — plan changes: upgrade invoices now (grants only from the
verified paid invoice), downgrade waits for renewal, never proration."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import select

from cloud.billing import ledger
from cloud.billing.models import CreditGrant, StripePriceBinding, StripeSubscription
from cloud.billing.seed import seed_commercial_v1
from cloud.billing.stripe_gateway import StripeGateway
from cloud.billing.stripe_service import CheckoutRejected, change_subscription_plan
from cloud.billing.stripe_webhooks import grant_from_paid_invoice
from cloud.config import Settings

pytestmark = pytest.mark.asyncio

SAME_ORIGIN = {"origin": "http://localhost:8100"}
CUS = "cus_test1"
PERIOD_START = datetime(2026, 7, 1, tzinfo=timezone.utc)
PERIOD_END = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _settings(**overrides) -> Settings:
    base = dict(
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        stripe_secret_key="sk_test_abc",
        stripe_publishable_key="pk_test_abc",
        stripe_webhook_secret="whsec_abc",
        stripe_livemode=False,
        base_url="http://localhost:8100",
    )
    return Settings(**{**base, **overrides})


class FakeStripe:
    """GET serves canonical objects; POST is recorded and echoes the sub."""

    def __init__(self):
        self.objects: dict[str, dict] = {}
        self.posts: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.posts.append((path, form))
            return httpx.Response(200, json=self.objects.get(path, {"id": "obj", "livemode": False}))
        obj = self.objects.get(path)
        if obj is None:
            return httpx.Response(404, json={"error": {"message": "no such object"}})
        return httpx.Response(200, json=obj)

    def gateway(self) -> StripeGateway:
        return StripeGateway("sk_test_abc", False,
                             transport=httpx.MockTransport(self.handler))

    def post_forms(self, path: str) -> list[dict]:
        return [form for p, form in self.posts if p == path]


def _stripe_sub(price_id="price_recurring_99", status="active") -> dict:
    return {
        "id": "sub_test1", "object": "subscription", "livemode": False,
        "status": status, "customer": CUS,
        "items": {"data": [{"id": "si_1", "price": {"id": price_id}}]},
        "current_period_start": int(PERIOD_START.timestamp()),
        "current_period_end": int(PERIOD_END.timestamp()),
        "cancel_at_period_end": False,
    }


async def _setup(db, account, *, current="recurring_99") -> FakeStripe:
    version = await seed_commercial_v1(db)
    for p in version.config_json["products"]:
        db.add(StripePriceBinding(
            livemode=False, product_key=p["key"],
            stripe_product_id=f"prod_{p['key']}", stripe_price_id=f"price_{p['key']}",
            price_usd_cents=p["price_usd_cents"], interval=p.get("interval"),
        ))
    ba = await ledger.ensure_billing_account(db, account.id)
    ba.stripe_customer_id = CUS
    db.add(StripeSubscription(
        account_id=account.id, stripe_subscription_id="sub_test1",
        product_key=current, stripe_price_id=f"price_{current}",
        status="active", current_period_start=PERIOD_START,
        current_period_end=PERIOD_END,
    ))
    await db.commit()
    fake = FakeStripe()
    fake.objects["/v1/subscriptions/sub_test1"] = _stripe_sub(f"price_{current}")
    return fake


async def _change(db, fake: FakeStripe, account, product_key: str) -> dict:
    gw = fake.gateway()
    try:
        result = await change_subscription_plan(db, gw, account, product_key)
    finally:
        await gw.aclose()
    await db.commit()
    return result


# ── Upgrades ─────────────────────────────────────────────────────────────────

async def test_upgrade_switches_price_and_invoices_now(db_session, account):
    fake = await _setup(db_session, account)
    result = await _change(db_session, fake, account, "recurring_199")
    assert result == {"applied": "upgrade_invoiced_now", "product_key": "recurring_199"}

    (form,) = fake.post_forms("/v1/subscriptions/sub_test1")
    assert form["items[0][id]"] == "si_1"
    assert form["items[0][price]"] == "price_recurring_199"
    assert form["billing_cycle_anchor"] == "now"
    assert form["proration_behavior"] == "none"
    assert form["payment_behavior"] == "pending_if_incomplete"

    # Nothing changes locally until the verified paid invoice: no grants,
    # mirror still shows the old plan (upgrade payment failure = no-op).
    mirror = (await db_session.execute(select(StripeSubscription))).scalar_one()
    assert mirror.product_key == "recurring_99"
    assert mirror.pending_product_key is None
    grants = list((await db_session.execute(select(CreditGrant))).scalars().all())
    assert grants == []


async def test_monthly_to_yearly_is_an_upgrade(db_session, account):
    fake = await _setup(db_session, account)
    result = await _change(db_session, fake, account, "recurring_99_yearly")
    assert result["applied"] == "upgrade_invoiced_now"
    (form,) = fake.post_forms("/v1/subscriptions/sub_test1")
    assert form["billing_cycle_anchor"] == "now"


async def test_upgrade_grants_full_bucket_from_verified_invoice(db_session, account):
    fake = await _setup(db_session, account)
    await _change(db_session, fake, account, "recurring_199")

    # Stripe then delivers the paid upgrade invoice at the new price.
    fake.objects["/v1/invoices/in_upgrade1"] = {
        "id": "in_upgrade1", "object": "invoice", "livemode": False,
        "status": "paid", "paid_out_of_band": False,
        "payment_intent": "pi_up1", "charge": "ch_up1",
        "currency": "usd", "amount_paid": 19_900, "tax": 0,
        "customer": CUS, "subscription": "sub_test1",
        "lines": {"data": [{
            "amount": 19_900, "price": {"id": "price_recurring_199"},
            "period": {"start": int(PERIOD_START.timestamp()),
                       "end": int(PERIOD_END.timestamp())},
        }]},
    }
    fake.objects["/v1/subscriptions/sub_test1"] = _stripe_sub("price_recurring_199")
    gw = fake.gateway()
    result = await grant_from_paid_invoice(db_session, gw, "evt_up", "in_upgrade1")
    await gw.aclose()
    await db_session.commit()
    assert result["granted"] is True
    assert result["credits"] == 19_900 + 5_100
    mirror = (await db_session.execute(select(StripeSubscription))).scalar_one()
    assert mirror.product_key == "recurring_199"


# ── Downgrades ───────────────────────────────────────────────────────────────

async def test_downgrade_waits_for_renewal(db_session, account):
    fake = await _setup(db_session, account, current="recurring_199")
    result = await _change(db_session, fake, account, "recurring_99")
    assert result == {"applied": "downgrade_at_renewal", "product_key": "recurring_99"}

    (form,) = fake.post_forms("/v1/subscriptions/sub_test1")
    assert form["items[0][price]"] == "price_recurring_99"
    assert form["proration_behavior"] == "none"
    assert "billing_cycle_anchor" not in form  # nothing charged until renewal
    assert "payment_behavior" not in form

    mirror = (await db_session.execute(select(StripeSubscription))).scalar_one()
    assert mirror.product_key == "recurring_199"  # current period unchanged
    assert mirror.pending_product_key == "recurring_99"


async def test_renewal_invoice_applies_pending_downgrade(db_session, account):
    fake = await _setup(db_session, account, current="recurring_199")
    await _change(db_session, fake, account, "recurring_99")

    fake.objects["/v1/invoices/in_renew1"] = {
        "id": "in_renew1", "object": "invoice", "livemode": False,
        "status": "paid", "paid_out_of_band": False,
        "payment_intent": "pi_rn1", "charge": "ch_rn1",
        "currency": "usd", "amount_paid": 9_900, "tax": 0,
        "customer": CUS, "subscription": "sub_test1",
        "lines": {"data": [{
            "amount": 9_900, "price": {"id": "price_recurring_99"},
            "period": {"start": int(PERIOD_START.timestamp()),
                       "end": int(PERIOD_END.timestamp())},
        }]},
    }
    fake.objects["/v1/subscriptions/sub_test1"] = _stripe_sub("price_recurring_99")
    gw = fake.gateway()
    for _ in range(2):  # replayed renewal webhook applies once
        result = await grant_from_paid_invoice(db_session, gw, "evt_rn", "in_renew1")
        assert result["granted"] is True
    await gw.aclose()
    await db_session.commit()

    mirror = (await db_session.execute(select(StripeSubscription))).scalar_one()
    assert mirror.product_key == "recurring_99"
    assert mirror.pending_product_key is None
    grants = list((await db_session.execute(select(CreditGrant))).scalars().all())
    assert sum(g.original_credits for g in grants) == 11_000


# ── Rejections ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("product_key, why", [
    ("recurring_99", "same plan"),
    ("topup_25", "not a subscription"),
    ("no_such_plan", "unknown key"),
])
async def test_rejected_changes_touch_nothing(db_session, account, product_key, why):
    fake = await _setup(db_session, account)
    with pytest.raises(CheckoutRejected):
        await _change(db_session, fake, account, product_key)
    assert fake.posts == [], why


async def test_change_without_live_subscription_rejected(db_session, account):
    fake = await _setup(db_session, account)
    fake.objects["/v1/subscriptions/sub_test1"] = _stripe_sub(status="canceled")
    with pytest.raises(CheckoutRejected):
        await _change(db_session, fake, account, "recurring_199")
    assert fake.posts == []


# ── Route ────────────────────────────────────────────────────────────────────

async def test_change_route(admin_client, db_session, account, monkeypatch):
    fake = await _setup(db_session, account)
    import cloud.billing.stripe_gateway as sg
    monkeypatch.setattr(sg, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        "cloud.api.billing_routes.StripeGateway",
        SimpleNamespace(from_settings=lambda settings=None: fake.gateway()),
    )
    resp = await admin_client.post("/api/billing/subscription/change",
                                   json={"product_key": "recurring_199"},
                                   headers=SAME_ORIGIN)
    assert resp.status_code == 200
    assert resp.json() == {"applied": "upgrade_invoiced_now",
                           "product_key": "recurring_199"}

    dup = await admin_client.post("/api/billing/subscription/change",
                                  json={"product_key": "recurring_99"},
                                  headers=SAME_ORIGIN)
    assert dup.status_code == 409  # already the current plan
