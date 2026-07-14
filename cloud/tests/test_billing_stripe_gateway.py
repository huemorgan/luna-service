"""039/007 — Stripe gateway: form encoding, signature verification, mode
safety, and the payments_enabled derivation (settings + bindings)."""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from cloud.billing.models import StripePriceBinding
from cloud.billing.seed import seed_billing, seed_commercial_v1
from cloud.billing.stripe_gateway import (
    StripeError,
    StripeGateway,
    form_encode,
    key_matches_mode,
    payments_enabled_for,
    stripe_settings_ok,
    verify_webhook_signature,
)
from cloud.config import Settings

pytestmark = pytest.mark.asyncio

SAME_ORIGIN = {"origin": "http://localhost:8100"}


# ── Form encoding ────────────────────────────────────────────────────────────

def test_form_encode_flattens_nested_structures():
    encoded = dict(form_encode({
        "mode": "subscription",
        "line_items": [{"price": "price_1", "quantity": 1}],
        "metadata": {"luna_account_id": "abc"},
        "expand": ["latest_invoice"],
        "cancel_at_period_end": True,
        "skip_me": None,
    }))
    assert encoded == {
        "mode": "subscription",
        "line_items[0][price]": "price_1",
        "line_items[0][quantity]": "1",
        "metadata[luna_account_id]": "abc",
        "expand[0]": "latest_invoice",
        "cancel_at_period_end": "true",
    }


# ── Webhook signatures ───────────────────────────────────────────────────────

SECRET = "whsec_testsecret"


def _sign(payload: bytes, secret: str = SECRET, ts: int = 1_700_000_000) -> str:
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256)
    return f"t={ts},v1={mac.hexdigest()}"


def test_signature_valid():
    body = b'{"id": "evt_1"}'
    header = _sign(body)
    assert verify_webhook_signature(body, header, SECRET, now=1_700_000_010)


def test_signature_rejects_wrong_secret_and_tampered_body():
    body = b'{"id": "evt_1"}'
    header = _sign(body)
    assert not verify_webhook_signature(body, header, "whsec_other", now=1_700_000_010)
    assert not verify_webhook_signature(b'{"id": "evt_2"}', header, SECRET, now=1_700_000_010)


def test_signature_rejects_stale_timestamp_replay():
    body = b"{}"
    header = _sign(body)
    assert not verify_webhook_signature(body, header, SECRET, now=1_700_000_000 + 301)


def test_signature_rejects_missing_or_malformed_header():
    assert not verify_webhook_signature(b"{}", None, SECRET)
    assert not verify_webhook_signature(b"{}", "", SECRET)
    assert not verify_webhook_signature(b"{}", "v1=abc", SECRET)
    assert not verify_webhook_signature(b"{}", "t=notanumber,v1=abc", SECRET)


def test_signature_accepts_any_matching_v1_candidate():
    body = b"{}"
    good = _sign(body).split("v1=")[1]
    header = f"t=1700000000,v1=deadbeef,v1={good}"
    assert verify_webhook_signature(body, header, SECRET, now=1_700_000_010)


# ── Mode safety ──────────────────────────────────────────────────────────────

def test_key_mode_matching():
    assert key_matches_mode("sk_test_abc", False)
    assert key_matches_mode("rk_test_abc", False)
    assert key_matches_mode("sk_live_abc", True)
    assert not key_matches_mode("sk_test_abc", True)
    assert not key_matches_mode("sk_live_abc", False)


def _settings(**overrides) -> Settings:
    base = dict(
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        stripe_secret_key="sk_test_abc",
        stripe_publishable_key="pk_test_abc",
        stripe_webhook_secret="whsec_abc",
        stripe_livemode=False,
    )
    return Settings(**{**base, **overrides})


def test_stripe_settings_ok_requires_full_consistent_config():
    assert stripe_settings_ok(_settings())
    assert not stripe_settings_ok(_settings(stripe_secret_key=""))
    assert not stripe_settings_ok(_settings(stripe_publishable_key=""))
    assert not stripe_settings_ok(_settings(stripe_webhook_secret=""))
    # declared live with a test key → fail closed
    assert not stripe_settings_ok(_settings(stripe_livemode=True))


def test_gateway_refuses_mode_mismatched_key():
    with pytest.raises(ValueError):
        StripeGateway("sk_test_abc", livemode=True)


# ── HTTP behavior (MockTransport — never the network) ────────────────────────

def _gateway(handler) -> StripeGateway:
    return StripeGateway("sk_test_abc", False, transport=httpx.MockTransport(handler))


async def test_post_sends_bracket_encoded_form():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content.decode()
        seen["idem"] = request.headers.get("Idempotency-Key")
        return httpx.Response(200, json={"id": "cs_1", "livemode": False})

    gw = _gateway(handler)
    out = await gw.post(
        "/v1/checkout/sessions",
        {"mode": "payment", "line_items": [{"price": "price_1", "quantity": 1}]},
        idempotency_key="op-123",
    )
    await gw.aclose()
    assert out["id"] == "cs_1"
    assert seen["path"] == "/v1/checkout/sessions"
    assert "line_items%5B0%5D%5Bprice%5D=price_1" in seen["body"]
    assert seen["idem"] == "op-123"


async def test_api_error_maps_to_stripe_error_with_retryability():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("declined"):
            return httpx.Response(402, json={"error": {"message": "Your card was declined.", "code": "card_declined"}})
        return httpx.Response(500, json={"error": {"message": "boom"}})

    gw = _gateway(handler)
    with pytest.raises(StripeError) as exc:
        await gw.get("/v1/declined")
    assert exc.value.code == "card_declined"
    assert not exc.value.retryable
    with pytest.raises(StripeError) as exc:
        await gw.get("/v1/other")
    assert exc.value.retryable
    await gw.aclose()


async def test_livemode_mismatch_on_response_object_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "in_1", "livemode": True})

    gw = _gateway(handler)
    with pytest.raises(StripeError):
        await gw.get("/v1/invoices/in_1")
    await gw.aclose()


# ── payments_enabled derivation ──────────────────────────────────────────────

async def _bind_all(db_session, config: dict, *, livemode: bool = False):
    for p in config["products"]:
        db_session.add(StripePriceBinding(
            livemode=livemode,
            product_key=p["key"],
            stripe_product_id=f"prod_{p['key']}",
            stripe_price_id=f"price_{p['key']}",
            price_usd_cents=p["price_usd_cents"],
            interval=p.get("interval"),
        ))
    await db_session.commit()


async def test_payments_disabled_without_stripe_settings(db_session):
    version = await seed_commercial_v1(db_session)
    await db_session.commit()
    config = version.config_json
    await _bind_all(db_session, config)
    assert not await payments_enabled_for(db_session, config, Settings(env="test"))


async def test_payments_disabled_until_every_product_bound(db_session):
    version = await seed_commercial_v1(db_session)
    await db_session.commit()
    config = version.config_json
    s = _settings()
    assert not await payments_enabled_for(db_session, config, s)  # no bindings
    await _bind_all(db_session, config)
    assert await payments_enabled_for(db_session, config, s)


async def test_payments_disabled_when_bindings_are_for_other_mode(db_session):
    version = await seed_commercial_v1(db_session)
    await db_session.commit()
    config = version.config_json
    await _bind_all(db_session, config, livemode=True)
    assert not await payments_enabled_for(db_session, config, _settings())


async def test_products_endpoint_derives_payments_enabled(admin_client, db_session, account, monkeypatch):
    await seed_billing(db_session)
    await db_session.commit()
    resp = await admin_client.get("/api/billing/products")
    assert resp.status_code == 200
    assert resp.json()["payments_enabled"] is False

    import cloud.billing.stripe_gateway as sg
    monkeypatch.setattr(sg, "get_settings", lambda: _settings())
    from cloud.billing.models import CommercialPricingVersion
    from sqlalchemy import select
    version = (await db_session.execute(select(CommercialPricingVersion))).scalars().first()
    await _bind_all(db_session, version.config_json)
    resp = await admin_client.get("/api/billing/products")
    assert resp.status_code == 200
    body = resp.json()
    assert body["payments_enabled"] is True
    # the flag flips, but internal fields still never leak
    assert "margin" not in json.dumps(body)
