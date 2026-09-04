"""Plan 102 — coupon codes: admin CRUD, customer redemption, used-coupon
records with redeemer identity."""

from __future__ import annotations

import re
import uuid

import pytest
from sqlalchemy import select

from cloud.billing.models import Coupon, CreditGrant
from cloud.billing.seed import seed_billing
from cloud.db.models import AuditLog

pytestmark = pytest.mark.asyncio

SAME_ORIGIN = {"origin": "http://localhost:8100"}
ADMIN_API = "/api/admin/pricing/coupons"
REDEEM = "/api/billing/coupons/redeem"


async def _seed(db_session):
    await seed_billing(db_session)
    await db_session.commit()


async def _mint(client, **overrides) -> dict:
    body = {"credits": 500, "reason": "test coupon", **overrides}
    resp = await client.post(ADMIN_API, json=body, headers=SAME_ORIGIN)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Admin auth & validation ──────────────────────────────────────────────────

async def test_coupon_admin_requires_admin(regular_client, anon_client):
    assert (await regular_client.get(ADMIN_API)).status_code == 403
    assert (await anon_client.get(ADMIN_API)).status_code == 401
    assert (await regular_client.post(
        ADMIN_API, json={"credits": 5, "reason": "x"}, headers=SAME_ORIGIN,
    )).status_code == 403


async def test_coupon_create_requires_reason(admin_client):
    for body in ({"credits": 100}, {"credits": 100, "reason": "  "}):
        resp = await admin_client.post(ADMIN_API, json=body, headers=SAME_ORIGIN)
        assert resp.status_code == 400
        assert "reason" in resp.json()["detail"].lower()


async def test_coupon_create_generates_code_and_audits(admin_client, db_session):
    out = await _mint(admin_client, credits=750)
    assert re.fullmatch(r"LUNA-[A-Z2-9]{4}-[A-Z2-9]{4}", out["code"])
    assert out["credits"] == 750
    assert out["status"] == "active"
    assert out["redeemed_account"] is None and out["redeemed_by"] is None
    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "pricing.coupon.create")
        )
    ).scalars().all()
    assert len(audit) == 1


async def test_coupon_explicit_code_canonicalized_and_unique(admin_client):
    out = await _mint(admin_client, code=" welcome100 ")
    assert out["code"] == "WELCOME100"
    resp = await admin_client.post(
        ADMIN_API, json={"credits": 5, "code": "welcome100", "reason": "dup"},
        headers=SAME_ORIGIN,
    )
    assert resp.status_code == 409


# ── Redemption ───────────────────────────────────────────────────────────────

async def test_redeem_grants_credits_and_marks_used(admin_client, db_session, account):
    await _seed(db_session)
    out = await _mint(admin_client, credits=500, expires_days=30)

    resp = await admin_client.post(
        REDEEM, json={"code": out["code"].lower()}, headers=SAME_ORIGIN,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["credits"] == 500
    assert body["expires_at"] is not None

    grant = (
        await db_session.execute(
            select(CreditGrant).where(CreditGrant.source_key == f"coupon:{out['id']}")
        )
    ).scalar_one()
    assert grant.account_id == account.id
    assert grant.original_credits == 500
    assert grant.visible_category == "gift"
    assert grant.source_type == "gift"

    summary = (await admin_client.get("/api/billing/summary")).json()
    assert summary["posted_balance_credits"] == 500

    # Used coupon stays listed with the redeeming account + user identity.
    rows = (await admin_client.get(ADMIN_API)).json()
    row = next(r for r in rows if r["id"] == out["id"])
    assert row["status"] == "used"
    assert row["redeemed_at"] is not None
    assert row["redeemed_account"]["name"] == "Test Account"
    assert row["redeemed_by"]["email"] == "vaselin@gmail.com"
    assert row["redeemed_by"]["name"] == "Admin"
    assert row["grant_id"] == str(grant.id)


async def test_redeem_used_coupon_conflicts(admin_client, db_session, account):
    await _seed(db_session)
    out = await _mint(admin_client)
    assert (await admin_client.post(
        REDEEM, json={"code": out["code"]}, headers=SAME_ORIGIN,
    )).status_code == 200
    resp = await admin_client.post(
        REDEEM, json={"code": out["code"]}, headers=SAME_ORIGIN,
    )
    assert resp.status_code == 409
    # No second grant lot.
    grants = (
        await db_session.execute(
            select(CreditGrant).where(CreditGrant.source_key == f"coupon:{out['id']}")
        )
    ).scalars().all()
    assert len(grants) == 1


async def test_redeem_unknown_code_404_and_requires_auth(admin_client, anon_client, account, db_session):
    assert (await anon_client.post(
        REDEEM, json={"code": "NOPE"}, headers=SAME_ORIGIN,
    )).status_code == 401
    assert (await admin_client.post(
        REDEEM, json={"code": "LUNA-NOPE-NOPE"}, headers=SAME_ORIGIN,
    )).status_code == 404


async def test_redeem_cross_origin_rejected(admin_client, account):
    resp = await admin_client.post(
        REDEEM, json={"code": "X"}, headers={"origin": "https://evil.example"},
    )
    assert resp.status_code == 403


async def test_redeem_expiry_falls_back_to_gift_default_days(admin_client, db_session, account):
    await _seed(db_session)
    out = await _mint(admin_client)  # no expires_days → gift_default_days (90)
    resp = await admin_client.post(
        REDEEM, json={"code": out["code"]}, headers=SAME_ORIGIN,
    )
    grant = (
        await db_session.execute(
            select(CreditGrant).where(CreditGrant.source_key == f"coupon:{out['id']}")
        )
    ).scalar_one()
    delta = grant.expires_at - grant.effective_at
    assert delta.days == 90
    assert resp.status_code == 200


# ── Delete ───────────────────────────────────────────────────────────────────

async def test_delete_unused_coupon(admin_client, db_session):
    out = await _mint(admin_client)
    resp = await admin_client.delete(f"{ADMIN_API}/{out['id']}", headers=SAME_ORIGIN)
    assert resp.status_code == 200
    left = (
        await db_session.execute(
            select(Coupon).where(Coupon.id == uuid.UUID(out["id"]))
        )
    ).scalar_one_or_none()
    assert left is None


async def test_delete_used_coupon_conflicts(admin_client, db_session, account):
    await _seed(db_session)
    out = await _mint(admin_client)
    assert (await admin_client.post(
        REDEEM, json={"code": out["code"]}, headers=SAME_ORIGIN,
    )).status_code == 200
    resp = await admin_client.delete(f"{ADMIN_API}/{out['id']}", headers=SAME_ORIGIN)
    assert resp.status_code == 409
    assert (await admin_client.delete(
        f"{ADMIN_API}/{uuid.uuid4()}", headers=SAME_ORIGIN,
    )).status_code == 404
