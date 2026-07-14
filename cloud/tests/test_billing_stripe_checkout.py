"""039/007 — checkout/portal service and routes, admin price bindings.

Every Stripe call goes through httpx.MockTransport — the suite never
touches the network. Checkout endpoints only return URLs; grant issuance
is webhook-only and covered elsewhere."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from cloud.billing.models import StripePriceBinding, StripeSubscription
from cloud.billing.seed import seed_commercial_v1
from cloud.billing.stripe_gateway import StripeGateway
from cloud.billing.stripe_service import (
    CheckoutRejected,
    create_portal_session,
    create_subscription_checkout,
    create_topup_checkout,
    ensure_stripe_customer,
)
from cloud.config import Settings
from cloud.db.models import Membership

pytestmark = pytest.mark.asyncio

SAME_ORIGIN = {"origin": "http://localhost:8100"}
ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


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
    """Request-recording Stripe backend behind httpx.MockTransport."""

    def __init__(self):
        self.requests: list[tuple[str, str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.requests.append((request.method, request.url.path, form))
        path = request.url.path
        if path == "/v1/customers":
            return httpx.Response(200, json={"id": "cus_test1", "livemode": False})
        if path == "/v1/checkout/sessions":
            return httpx.Response(200, json={
                "id": "cs_test1", "livemode": False,
                "url": "https://checkout.stripe.com/c/pay/cs_test1",
            })
        if path == "/v1/billing_portal/sessions":
            return httpx.Response(200, json={
                "id": "bps_test1", "livemode": False,
                "url": "https://billing.stripe.com/p/session/bps_test1",
            })
        return httpx.Response(404, json={"error": {"message": f"no fake for {path}"}})

    def gateway(self) -> StripeGateway:
        return StripeGateway("sk_test_abc", False,
                             transport=httpx.MockTransport(self.handler))

    def calls(self, path: str) -> list[dict]:
        return [form for _, p, form in self.requests if p == path]


async def _seed_bound_catalog(db_session) -> dict:
    version = await seed_commercial_v1(db_session)
    config = version.config_json
    for p in config["products"]:
        db_session.add(StripePriceBinding(
            livemode=False,
            product_key=p["key"],
            stripe_product_id=f"prod_{p['key']}",
            stripe_price_id=f"price_{p['key']}",
            price_usd_cents=p["price_usd_cents"],
            interval=p.get("interval"),
        ))
    await db_session.commit()
    return config


# ── Customer creation ────────────────────────────────────────────────────────

async def test_one_stripe_customer_per_account(db_session, account, admin_user):
    fake = FakeStripe()
    gw = fake.gateway()
    first = await ensure_stripe_customer(db_session, gw, account, admin_user)
    second = await ensure_stripe_customer(db_session, gw, account, admin_user)
    await gw.aclose()
    assert first == second == "cus_test1"
    creates = fake.calls("/v1/customers")
    assert len(creates) == 1
    assert creates[0]["metadata[luna_account_id]"] == str(account.id)


# ── Subscription checkout ────────────────────────────────────────────────────

async def test_subscription_checkout_happy_path(db_session, account, admin_user):
    await _seed_bound_catalog(db_session)
    fake = FakeStripe()
    gw = fake.gateway()
    url = await create_subscription_checkout(
        db_session, gw, account, admin_user, "recurring_99", settings=_settings()
    )
    await gw.aclose()
    assert url.startswith("https://checkout.stripe.com/")
    (session,) = fake.calls("/v1/checkout/sessions")
    assert session["mode"] == "subscription"
    assert session["line_items[0][price]"] == "price_recurring_99"
    assert session["metadata[luna_product_key]"] == "recurring_99"
    assert session["metadata[luna_account_id]"] == str(account.id)
    assert "metadata[luna_operation_id]" in session
    # the subscription object itself carries the same metadata for webhooks
    assert session["subscription_data[metadata][luna_product_key]"] == "recurring_99"
    assert session["customer"] == "cus_test1"


async def test_subscription_checkout_rejects_unknown_and_topup_keys(db_session, account, admin_user):
    await _seed_bound_catalog(db_session)
    fake = FakeStripe()
    gw = fake.gateway()
    with pytest.raises(CheckoutRejected):
        await create_subscription_checkout(
            db_session, gw, account, admin_user, "nope", settings=_settings())
    with pytest.raises(CheckoutRejected):
        await create_subscription_checkout(
            db_session, gw, account, admin_user, "topup_10", settings=_settings())
    await gw.aclose()
    assert not fake.calls("/v1/checkout/sessions")


async def test_subscription_checkout_only_first_subscription(db_session, account, admin_user):
    await _seed_bound_catalog(db_session)
    db_session.add(StripeSubscription(
        account_id=account.id, stripe_subscription_id="sub_1",
        product_key="hobby_19", status="active",
    ))
    await db_session.commit()
    fake = FakeStripe()
    gw = fake.gateway()
    with pytest.raises(CheckoutRejected, match="already has a subscription"):
        await create_subscription_checkout(
            db_session, gw, account, admin_user, "recurring_99", settings=_settings())
    await gw.aclose()


async def test_canceled_subscription_frees_the_slot(db_session, account, admin_user):
    await _seed_bound_catalog(db_session)
    db_session.add(StripeSubscription(
        account_id=account.id, stripe_subscription_id="sub_old",
        product_key="hobby_19", status="canceled",
    ))
    await db_session.commit()
    fake = FakeStripe()
    gw = fake.gateway()
    url = await create_subscription_checkout(
        db_session, gw, account, admin_user, "recurring_99", settings=_settings())
    await gw.aclose()
    assert url


async def test_missing_or_drifted_binding_blocks_checkout(db_session, account, admin_user):
    version = await seed_commercial_v1(db_session)
    await db_session.commit()
    fake = FakeStripe()
    gw = fake.gateway()
    with pytest.raises(CheckoutRejected, match="not available"):
        await create_subscription_checkout(
            db_session, gw, account, admin_user, "recurring_99", settings=_settings())
    # bind at the WRONG amount — catalog drifted after attach
    db_session.add(StripePriceBinding(
        livemode=False, product_key="recurring_99",
        stripe_product_id="prod_x", stripe_price_id="price_x",
        price_usd_cents=10_000, interval="month",
    ))
    await db_session.commit()
    with pytest.raises(CheckoutRejected, match="being updated"):
        await create_subscription_checkout(
            db_session, gw, account, admin_user, "recurring_99", settings=_settings())
    await gw.aclose()
    assert not fake.calls("/v1/checkout/sessions")


# ── Top-up checkout ──────────────────────────────────────────────────────────

async def test_topup_checkout_resolves_step_server_side(db_session, account, admin_user):
    config = await _seed_bound_catalog(db_session)
    assert 2_500 in config["topup_steps_usd_cents"]
    fake = FakeStripe()
    gw = fake.gateway()
    url = await create_topup_checkout(
        db_session, gw, account, admin_user, 2_500, settings=_settings())
    await gw.aclose()
    assert url
    (session,) = fake.calls("/v1/checkout/sessions")
    assert session["mode"] == "payment"
    assert session["line_items[0][price]"] == "price_topup_25"
    assert session["metadata[luna_expected_credits]"] == "2500"
    assert session["payment_intent_data[metadata][luna_product_key]"] == "topup_25"


async def test_topup_checkout_rejects_arbitrary_amounts(db_session, account, admin_user):
    await _seed_bound_catalog(db_session)
    fake = FakeStripe()
    gw = fake.gateway()
    for bad in (1, 2_000, 999_999):
        with pytest.raises(CheckoutRejected, match="Unknown top-up"):
            await create_topup_checkout(
                db_session, gw, account, admin_user, bad, settings=_settings())
    await gw.aclose()
    assert not fake.calls("/v1/checkout/sessions")


# ── Portal ───────────────────────────────────────────────────────────────────

async def test_portal_session(db_session, account, admin_user):
    fake = FakeStripe()
    gw = fake.gateway()
    url = await create_portal_session(
        db_session, gw, account, admin_user, settings=_settings())
    await gw.aclose()
    assert url.startswith("https://billing.stripe.com/")
    (call,) = fake.calls("/v1/billing_portal/sessions")
    assert call["customer"] == "cus_test1"
    assert call["return_url"] == "http://localhost:8100/billing"


# ── Routes ───────────────────────────────────────────────────────────────────

def _patch_route_gateway(monkeypatch, fake: FakeStripe):
    import cloud.billing.stripe_gateway as sg
    monkeypatch.setattr(sg, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        "cloud.api.billing_routes.StripeGateway",
        SimpleNamespace(from_settings=lambda settings=None: fake.gateway()),
    )


async def test_checkout_route_503_when_stripe_unconfigured(admin_client, db_session, account):
    await _seed_bound_catalog(db_session)
    resp = await admin_client.post("/api/billing/checkout/subscription",
                                   json={"product_key": "recurring_99"},
                                   headers=SAME_ORIGIN)
    assert resp.status_code == 503


async def test_checkout_route_rejects_foreign_origin(admin_client, db_session, account, monkeypatch):
    await _seed_bound_catalog(db_session)
    _patch_route_gateway(monkeypatch, FakeStripe())
    resp = await admin_client.post("/api/billing/checkout/subscription",
                                   json={"product_key": "recurring_99"},
                                   headers={"origin": "https://evil.example"})
    assert resp.status_code == 403


async def test_checkout_route_owner_only(regular_client, regular_user, db_session, account, monkeypatch):
    await _seed_bound_catalog(db_session)
    db_session.add(Membership(account_id=account.id, user_id=regular_user.id, role="member"))
    await db_session.commit()
    _patch_route_gateway(monkeypatch, FakeStripe())
    resp = await regular_client.post("/api/billing/checkout/subscription",
                                     json={"product_key": "recurring_99"},
                                     headers=SAME_ORIGIN)
    assert resp.status_code == 403


async def test_checkout_routes_happy_paths(admin_client, db_session, account, monkeypatch):
    await _seed_bound_catalog(db_session)
    fake = FakeStripe()
    _patch_route_gateway(monkeypatch, fake)

    resp = await admin_client.post("/api/billing/checkout/subscription",
                                   json={"product_key": "recurring_99"},
                                   headers=SAME_ORIGIN)
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://checkout.stripe.com/")

    resp = await admin_client.post("/api/billing/checkout/topup",
                                   json={"amount_usd_cents": 1_000},
                                   headers=SAME_ORIGIN)
    assert resp.status_code == 200

    resp = await admin_client.post("/api/billing/portal", headers=SAME_ORIGIN)
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://billing.stripe.com/")

    # the two checkouts share one customer
    assert len(fake.calls("/v1/customers")) == 1


async def test_topup_route_rejects_tampered_amount(admin_client, db_session, account, monkeypatch):
    await _seed_bound_catalog(db_session)
    _patch_route_gateway(monkeypatch, FakeStripe())
    resp = await admin_client.post("/api/billing/checkout/topup",
                                   json={"amount_usd_cents": 1_234},
                                   headers=SAME_ORIGIN)
    assert resp.status_code == 409


async def test_existing_subscription_conflicts_on_route(admin_client, db_session, account, monkeypatch):
    await _seed_bound_catalog(db_session)
    db_session.add(StripeSubscription(
        account_id=account.id, stripe_subscription_id="sub_1",
        product_key="hobby_19", status="active",
    ))
    await db_session.commit()
    _patch_route_gateway(monkeypatch, FakeStripe())
    resp = await admin_client.post("/api/billing/checkout/subscription",
                                   json={"product_key": "recurring_99"},
                                   headers=SAME_ORIGIN)
    assert resp.status_code == 409


# ── Admin bindings ───────────────────────────────────────────────────────────

async def test_bindings_listing_reports_missing_then_bound(admin_client, db_session):
    version = await seed_commercial_v1(db_session)
    await db_session.commit()
    resp = await admin_client.get("/api/admin/pricing/stripe-bindings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["payments_enabled"] is False
    assert "recurring_99" in body["missing"]
    assert body["bindings"] == []

    resp = await admin_client.put(
        "/api/admin/pricing/stripe-bindings/recurring_99",
        json={"stripe_product_id": "prod_a", "stripe_price_id": "price_a",
              "reason": "attach test binding"},
        headers=SAME_ORIGIN,
    )
    assert resp.status_code == 200
    body = (await admin_client.get("/api/admin/pricing/stripe-bindings")).json()
    assert "recurring_99" not in body["missing"]
    (b,) = body["bindings"]
    # the binding records the catalog amount it was attached against
    assert b["price_usd_cents"] == 9_900
    assert b["interval"] == "month"


async def test_binding_upsert_requires_reason_and_known_product(admin_client, db_session):
    await seed_commercial_v1(db_session)
    await db_session.commit()
    resp = await admin_client.put(
        "/api/admin/pricing/stripe-bindings/recurring_99",
        json={"stripe_product_id": "prod_a", "stripe_price_id": "price_a"},
        headers=SAME_ORIGIN,
    )
    assert resp.status_code == 400
    resp = await admin_client.put(
        "/api/admin/pricing/stripe-bindings/not_a_product",
        json={"stripe_product_id": "prod_a", "stripe_price_id": "price_a",
              "reason": "x"},
        headers=SAME_ORIGIN,
    )
    assert resp.status_code == 404


async def test_bindings_sync_binds_matching_prices(admin_client, db_session, monkeypatch):
    version = await seed_commercial_v1(db_session)
    await db_session.commit()
    config = version.config_json

    def lookup_key(p):
        if p["kind"] == "subscription" and p.get("interval") == "month":
            return f"{p['key']}_monthly"
        return p["key"]

    prices = []
    for p in config["products"]:
        amount = p["price_usd_cents"]
        if p["key"] == "topup_50":
            amount = 1  # deliberate mismatch — must be reported, not bound
        prices.append({
            "id": f"price_{p['key']}",
            "product": f"prod_{p['key']}",
            "lookup_key": lookup_key(p),
            "unit_amount": amount,
            "currency": "usd",
            "livemode": False,
            "recurring": {"interval": p["interval"]} if p.get("interval") else None,
        })

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/prices"
        return httpx.Response(200, json={"object": "list", "data": prices})

    import cloud.billing.stripe_gateway as sg
    monkeypatch.setattr(sg, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        "cloud.api.billing_admin_routes.StripeGateway",
        SimpleNamespace(from_settings=lambda settings=None: StripeGateway(
            "sk_test_abc", False, transport=httpx.MockTransport(handler))),
    )
    monkeypatch.setattr("cloud.api.billing_admin_routes.get_settings", lambda: _settings())

    resp = await admin_client.post("/api/admin/pricing/stripe-bindings/sync",
                                   json={"reason": "bind test mode"},
                                   headers=SAME_ORIGIN)
    assert resp.status_code == 200
    body = resp.json()
    assert "recurring_99_yearly" in body["bound"]
    assert body["mismatched"][0]["lookup_key"] == "topup_50"
    assert body["missing"] == []
    # one product failed to bind, so payments stay off
    assert body["payments_enabled"] is False
