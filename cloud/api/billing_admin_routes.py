"""Admin API for pricing (039/002): versions, assignments, rollouts, costs.

Every mutation requires admin auth, passes the same-origin CSRF guard,
writes a before/after audit row, and — where financial (publish, retire,
rollout, manual assignment) — a non-empty reason.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from cloud.auth.deps import enforce_same_origin, require_admin
from cloud.billing import assignments as assignments_svc
from cloud.billing import versions as versions_svc
from cloud.billing.models import (
    AccountBalanceProjection,
    BillingHold,
    BillingJob,
    CommercialPricingAssignment,
    CommercialPricingRollout,
    CommercialPricingVersion,
    ProviderCostRate,
    ProviderCostVersion,
    StripePriceBinding,
)
from cloud.billing.stripe_gateway import (
    StripeError,
    StripeGateway,
    payments_enabled_for,
    stripe_settings_ok,
)
from cloud.config import get_settings
from cloud.db.models import Account, AuditLog, User
from cloud.db.session import get_session as get_db_session

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/pricing", tags=["pricing-admin"],
                   dependencies=[Depends(enforce_same_origin)])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _audit(db, request: Request, actor: User, *, action: str, target: str,
           reason: str | None = None, before: dict | None = None,
           after: dict | None = None) -> None:
    db.add(AuditLog(
        actor_user_id=actor.id,
        actor_ip=_client_ip(request),
        action=action,
        target=target,
        metadata_={"reason": reason} if reason else None,
        before_state=before,
        after_state=after,
    ))


def _require_reason(reason: str | None) -> str:
    if not reason or not reason.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A reason is required for financial changes")
    return reason.strip()


def _version_state(v: CommercialPricingVersion) -> dict:
    return {"status": v.status, "config_hash": v.config_hash, "name": v.name}


def _version_out(v: CommercialPricingVersion, *, with_config: bool = False) -> dict:
    out = {
        "id": str(v.id),
        "version_number": v.version_number,
        "name": v.name,
        "status": v.status,
        "parent_version_id": str(v.parent_version_id) if v.parent_version_id else None,
        "config_hash": v.config_hash,
        "config_schema_version": v.config_schema_version,
        "notes": v.notes,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "published_at": v.published_at.isoformat() if v.published_at else None,
    }
    if with_config:
        out["config"] = v.config_json
    return out


async def _get_version(db, version_id: uuid.UUID) -> CommercialPricingVersion:
    version = await db.get(CommercialPricingVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    return version


# ── Overview ─────────────────────────────────────────────────────────────────

@router.get("/overview")
async def overview(admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        now = datetime.now(timezone.utc)
        default_id = None
        try:
            default_id = await assignments_svc.default_version_id(db, now=now)
        except assignments_svc.AssignmentError:
            pass
        status_counts = dict(
            (await db.execute(
                select(CommercialPricingVersion.status, func.count())
                .group_by(CommercialPricingVersion.status)
            )).all()
        )
        # Projections are a rebuildable read model — good enough for an
        # operator overview, never financial authority.
        liability = (await db.execute(
            select(func.coalesce(func.sum(AccountBalanceProjection.posted_balance_credits), 0))
            .where(AccountBalanceProjection.posted_balance_credits > 0)
        )).scalar_one()
        debt = (await db.execute(
            select(func.coalesce(func.sum(AccountBalanceProjection.debt_credits), 0))
        )).scalar_one()
        dead_jobs = (await db.execute(
            select(func.count()).select_from(BillingJob).where(BillingJob.status == "dead")
        )).scalar_one()
        reconciliation_holds = (await db.execute(
            select(func.count()).select_from(BillingHold)
            .where(BillingHold.status == "needs_reconciliation")
        )).scalar_one()
        assigned_accounts = (await db.execute(
            select(func.count(func.distinct(CommercialPricingAssignment.account_id)))
        )).scalar_one()
        default_version = await db.get(CommercialPricingVersion, default_id) if default_id else None
        return {
            "default_version": _version_out(default_version) if default_version else None,
            "version_status_counts": status_counts,
            "customer_liability_credits": liability,
            "uncovered_debt_credits": debt,
            "dead_billing_jobs": dead_jobs,
            "needs_reconciliation_holds": reconciliation_holds,
            "assigned_accounts": assigned_accounts,
        }


# ── Versions ─────────────────────────────────────────────────────────────────

@router.get("/versions")
async def list_versions(admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        rows = (await db.execute(
            select(CommercialPricingVersion)
            .order_by(CommercialPricingVersion.version_number.desc())
        )).scalars().all()
        return {"versions": [_version_out(v) for v in rows]}


@router.get("/versions/{version_id}")
async def get_version(version_id: uuid.UUID, admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        version = await _get_version(db, version_id)
        out = _version_out(version, with_config=True)
        if version.parent_version_id:
            parent = await db.get(CommercialPricingVersion, version.parent_version_id)
            if parent is not None:
                out["diff_vs_parent"] = versions_svc.config_diff(
                    parent.config_json, version.config_json
                )
        out["uncovered_models"] = await versions_svc.uncovered_gateway_models(
            db, version.config_json
        )
        return out


class CloneRequest(BaseModel):
    name: str | None = None
    notes: str | None = None


@router.post("/versions/{version_id}/clone")
async def clone_version(version_id: uuid.UUID, body: CloneRequest, request: Request,
                        admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        try:
            draft = await versions_svc.clone_version(
                db, version_id, name=body.name, created_by=admin.id, notes=body.notes
            )
        except versions_svc.ConfigValidationError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        _audit(db, request, admin, action="pricing.version.clone",
               target=f"version:{draft.version_number}",
               after=_version_state(draft))
        await db.commit()
        return _version_out(draft, with_config=True)


class UpdateDraftRequest(BaseModel):
    config: dict | None = None
    name: str | None = None
    notes: str | None = None


@router.put("/versions/{version_id}")
async def update_draft(version_id: uuid.UUID, body: UpdateDraftRequest, request: Request,
                       admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        version = await _get_version(db, version_id)
        before = _version_state(version)
        try:
            await versions_svc.update_draft(
                db, version_id, config=body.config, name=body.name, notes=body.notes
            )
        except versions_svc.ConfigValidationError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        _audit(db, request, admin, action="pricing.version.update_draft",
               target=f"version:{version.version_number}",
               before=before, after=_version_state(version))
        await db.commit()
        return _version_out(version, with_config=True)


class FinancialActionRequest(BaseModel):
    reason: str = Field(default="")


@router.post("/versions/{version_id}/publish")
async def publish_version(version_id: uuid.UUID, body: FinancialActionRequest,
                          request: Request, admin: User = Depends(require_admin)):
    reason = _require_reason(body.reason)
    async with get_db_session() as db:
        version = await _get_version(db, version_id)
        before = _version_state(version)
        try:
            await versions_svc.publish_version(db, version_id)
        except versions_svc.ConfigValidationError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        _audit(db, request, admin, action="pricing.version.publish",
               target=f"version:{version.version_number}", reason=reason,
               before=before, after=_version_state(version))
        await db.commit()
        return _version_out(version)


@router.post("/versions/{version_id}/retire")
async def retire_version(version_id: uuid.UUID, body: FinancialActionRequest,
                         request: Request, admin: User = Depends(require_admin)):
    reason = _require_reason(body.reason)
    async with get_db_session() as db:
        version = await _get_version(db, version_id)
        before = _version_state(version)
        try:
            await versions_svc.retire_version(db, version_id)
        except versions_svc.ConfigValidationError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        _audit(db, request, admin, action="pricing.version.retire",
               target=f"version:{version.version_number}", reason=reason,
               before=before, after=_version_state(version))
        await db.commit()
        return _version_out(version)


@router.get("/versions/{version_id}/diff/{other_id}")
async def diff_versions(version_id: uuid.UUID, other_id: uuid.UUID,
                        admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        a = await _get_version(db, version_id)
        b = await _get_version(db, other_id)
        return {
            "from": _version_out(a),
            "to": _version_out(b),
            "diff": versions_svc.config_diff(a.config_json, b.config_json),
        }


# ── Provider-cost versions ───────────────────────────────────────────────────

def _cost_version_out(v: ProviderCostVersion) -> dict:
    return {
        "id": str(v.id),
        "version_number": v.version_number,
        "status": v.status,
        "effective_at": v.effective_at.isoformat() if v.effective_at else None,
        "config_hash": v.config_hash,
        "notes": v.notes,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "published_at": v.published_at.isoformat() if v.published_at else None,
    }


@router.get("/provider-costs")
async def list_provider_costs(admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        rows = (await db.execute(
            select(ProviderCostVersion).order_by(ProviderCostVersion.version_number.desc())
        )).scalars().all()
        return {"versions": [_cost_version_out(v) for v in rows]}


@router.get("/provider-costs/{version_id}")
async def get_provider_cost(version_id: uuid.UUID, admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        version = await db.get(ProviderCostVersion, version_id)
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
        rates = (await db.execute(
            select(ProviderCostRate)
            .where(ProviderCostRate.provider_cost_version_id == version_id)
            .order_by(ProviderCostRate.provider, ProviderCostRate.sku, ProviderCostRate.dimension)
        )).scalars().all()
        out = _cost_version_out(version)
        out["rates"] = [
            {
                "provider": r.provider, "sku": r.sku, "dimension": r.dimension,
                "unit": r.unit, "rate_numerator": r.rate_numerator,
                "rate_denominator": r.rate_denominator, "quality": r.quality,
                "source_url": r.source_url,
            }
            for r in rates
        ]
        return out


class ProviderCostDraftRequest(BaseModel):
    rates: list[dict]
    notes: str | None = None


@router.post("/provider-costs")
async def create_provider_cost_draft(body: ProviderCostDraftRequest, request: Request,
                                     admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        try:
            version = await versions_svc.create_provider_cost_draft(
                db, rates=body.rates, notes=body.notes, created_by=admin.id
            )
        except versions_svc.ConfigValidationError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        _audit(db, request, admin, action="pricing.provider_costs.create_draft",
               target=f"provider_cost_version:{version.version_number}",
               after={"status": version.status, "config_hash": version.config_hash})
        await db.commit()
        return _cost_version_out(version)


class ProviderCostPublishRequest(BaseModel):
    effective_at: datetime | None = None
    reason: str = Field(default="")


@router.post("/provider-costs/{version_id}/publish")
async def publish_provider_cost(version_id: uuid.UUID, body: ProviderCostPublishRequest,
                                request: Request, admin: User = Depends(require_admin)):
    # Global and effective-dated by construction: there is no account or
    # cohort parameter on this endpoint.
    reason = _require_reason(body.reason)
    async with get_db_session() as db:
        version = await db.get(ProviderCostVersion, version_id)
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
        before = {"status": version.status}
        try:
            await versions_svc.publish_provider_cost_version(
                db, version_id,
                effective_at=body.effective_at or datetime.now(timezone.utc),
            )
        except versions_svc.ConfigValidationError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        _audit(db, request, admin, action="pricing.provider_costs.publish",
               target=f"provider_cost_version:{version.version_number}", reason=reason,
               before=before,
               after={"status": version.status,
                      "effective_at": version.effective_at.isoformat()})
        await db.commit()
        return _cost_version_out(version)


# ── Assignments ──────────────────────────────────────────────────────────────

def _assignment_out(a: CommercialPricingAssignment) -> dict:
    return {
        "id": str(a.id),
        "account_id": str(a.account_id),
        "commercial_pricing_version_id": str(a.commercial_pricing_version_id),
        "effective_at": a.effective_at.isoformat() if a.effective_at else None,
        "ends_at": a.ends_at.isoformat() if a.ends_at else None,
        "source": a.source,
        "audit_ref": a.audit_ref,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("/accounts/{account_id}/assignments")
async def list_assignments(account_id: uuid.UUID, admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        rows = (await db.execute(
            select(CommercialPricingAssignment)
            .where(CommercialPricingAssignment.account_id == account_id)
            .order_by(CommercialPricingAssignment.effective_at.desc())
        )).scalars().all()
        return {"assignments": [_assignment_out(a) for a in rows]}


class AssignRequest(BaseModel):
    account_id: uuid.UUID
    version_id: uuid.UUID
    effective_at: datetime | None = None
    reason: str = Field(default="")


@router.post("/assignments")
async def create_assignment(body: AssignRequest, request: Request,
                            admin: User = Depends(require_admin)):
    reason = _require_reason(body.reason)
    async with get_db_session() as db:
        account = await db.get(Account, body.account_id)
        if account is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
        try:
            assignment = await assignments_svc.assign_version(
                db, body.account_id, body.version_id,
                effective_at=body.effective_at or datetime.now(timezone.utc),
                source="manual_test", actor_user_id=admin.id,
            )
        except assignments_svc.AssignmentError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        _audit(db, request, admin, action="pricing.assignment.create",
               target=f"account:{body.account_id}", reason=reason,
               after=_assignment_out(assignment))
        await db.commit()
        return _assignment_out(assignment)


# ── Rollouts ─────────────────────────────────────────────────────────────────

def _rollout_out(r: CommercialPricingRollout) -> dict:
    return {
        "id": str(r.id),
        "commercial_pricing_version_id": str(r.commercial_pricing_version_id),
        "audience": r.audience,
        "selected_account_ids": r.selected_account_ids,
        "effective_at": r.effective_at.isoformat() if r.effective_at else None,
        "migration_policy": r.migration_policy,
        "status": r.status,
        "accounts_scheduled": r.accounts_scheduled,
        "accounts_applied": r.accounts_applied,
        "accounts_failed": r.accounts_failed,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/rollouts")
async def list_rollouts(admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        rows = (await db.execute(
            select(CommercialPricingRollout)
            .order_by(CommercialPricingRollout.created_at.desc())
        )).scalars().all()
        return {"rollouts": [_rollout_out(r) for r in rows]}


class RolloutRequest(BaseModel):
    version_id: uuid.UUID
    audience: str
    effective_at: datetime | None = None
    selected_account_ids: list[uuid.UUID] | None = None
    reason: str = Field(default="")


@router.post("/rollouts")
async def create_rollout(body: RolloutRequest, request: Request,
                         admin: User = Depends(require_admin)):
    reason = _require_reason(body.reason)
    async with get_db_session() as db:
        try:
            rollout = await assignments_svc.create_rollout(
                db, body.version_id,
                audience=body.audience,
                effective_at=body.effective_at or datetime.now(timezone.utc),
                selected_account_ids=body.selected_account_ids,
                created_by=admin.id,
            )
        except assignments_svc.AssignmentError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        _audit(db, request, admin, action="pricing.rollout.create",
               target=f"rollout:{rollout.id}", reason=reason,
               after=_rollout_out(rollout))
        await db.commit()
        return _rollout_out(rollout)


# ── Gifts (039/005) ──────────────────────────────────────────────────────────

class GiftRequest(BaseModel):
    account_id: uuid.UUID
    credits: int = Field(gt=0)
    expires_days: int | None = Field(default=None, gt=0)
    idempotency_key: str | None = None
    reason: str = Field(default="")


@router.post("/gifts")
async def create_gift(body: GiftRequest, request: Request,
                      admin: User = Depends(require_admin)):
    reason = _require_reason(body.reason)
    async with get_db_session() as db:
        account = await db.get(Account, body.account_id)
        if account is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
        from cloud.billing.grants import account_config, grant_admin_gift
        from cloud.billing.rating import RatingUnavailable

        expires_days = body.expires_days
        if expires_days is None:
            try:
                config = await account_config(db, body.account_id)
                expires_days = int(config.get("gift_default_days") or 0) or None
            except RatingUnavailable:
                expires_days = None
        source_key = body.idempotency_key or f"admin_gift:{uuid.uuid4()}"
        grant = await grant_admin_gift(
            db, body.account_id,
            credits=body.credits,
            expires_days=expires_days,
            source_key=source_key,
            actor=f"admin:{admin.id}",
            reason=reason,
        )
        _audit(db, request, admin, action="pricing.gift.create",
               target=f"account:{body.account_id}", reason=reason,
               after={"grant_id": str(grant.id), "credits": body.credits,
                      "expires_days": expires_days, "source_key": source_key})
        await db.commit()
        return {
            "grant_id": str(grant.id),
            "account_id": str(body.account_id),
            "credits": grant.original_credits,
            "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            "source_key": grant.source_key,
        }


# ── Coverage helper for the UI warning banner ────────────────────────────────

@router.get("/models-coverage/{version_id}")
async def models_coverage(version_id: uuid.UUID, admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        version = await _get_version(db, version_id)
        return {
            "uncovered_models": await versions_svc.uncovered_gateway_models(
                db, version.config_json
            )
        }


# ── Stripe price bindings (039/007) ──────────────────────────────────────────
# Bindings gate checkout activation: payments stay disabled until every
# product in the default published catalog is bound to a Stripe Price for
# the declared mode. Publication (002) stays decoupled from Stripe.

def _stripe_lookup_key(product: dict) -> str:
    """006 naming: monthly subscriptions carry a `_monthly` suffix in Stripe;
    yearly and top-up keys match the catalog key exactly."""
    key = product["key"]
    if product.get("kind") == "subscription" and product.get("interval") == "month":
        return f"{key}_monthly"
    return key


async def _default_config(db) -> dict:
    try:
        version_id = await assignments_svc.default_version_id(db)
    except Exception:
        raise HTTPException(status.HTTP_409_CONFLICT, "No published pricing version")
    version = await db.get(CommercialPricingVersion, version_id)
    return version.config_json


@router.get("/stripe-bindings")
async def list_stripe_bindings(admin: User = Depends(require_admin)):
    s = get_settings()
    async with get_db_session() as db:
        config = await _default_config(db)
        products = {p["key"]: p for p in config.get("products") or []}
        bindings = (
            await db.execute(
                select(StripePriceBinding).where(
                    StripePriceBinding.livemode == s.stripe_livemode
                )
            )
        ).scalars().all()
        by_key = {b.product_key: b for b in bindings}
        drifted = [
            k for k, p in products.items()
            if k in by_key and (
                by_key[k].price_usd_cents != p["price_usd_cents"]
                or (by_key[k].interval or None) != (p.get("interval") or None)
            )
        ]
        return {
            "livemode": s.stripe_livemode,
            "stripe_settings_ok": stripe_settings_ok(s),
            "bindings": [
                {
                    "product_key": b.product_key,
                    "stripe_product_id": b.stripe_product_id,
                    "stripe_price_id": b.stripe_price_id,
                    "price_usd_cents": b.price_usd_cents,
                    "interval": b.interval,
                    "updated_at": b.updated_at.isoformat(),
                }
                for b in sorted(bindings, key=lambda b: b.product_key)
            ],
            "missing": sorted(set(products) - set(by_key)),
            "drifted": sorted(drifted),
            "payments_enabled": await payments_enabled_for(db, config, s),
        }


class BindingBody(BaseModel):
    stripe_product_id: str = Field(min_length=1)
    stripe_price_id: str = Field(min_length=1)
    reason: str = Field(default="")


@router.put("/stripe-bindings/{product_key}")
async def upsert_stripe_binding(product_key: str, body: BindingBody,
                                request: Request, admin: User = Depends(require_admin)):
    reason = _require_reason(body.reason)
    s = get_settings()
    async with get_db_session() as db:
        config = await _default_config(db)
        product = next((p for p in config.get("products") or []
                        if p["key"] == product_key), None)
        if product is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                f"No product '{product_key}' in the default catalog")
        binding = (
            await db.execute(
                select(StripePriceBinding).where(
                    StripePriceBinding.livemode == s.stripe_livemode,
                    StripePriceBinding.product_key == product_key,
                )
            )
        ).scalar_one_or_none()
        before = None
        if binding is None:
            binding = StripePriceBinding(livemode=s.stripe_livemode, product_key=product_key,
                                         stripe_product_id="", stripe_price_id="",
                                         price_usd_cents=0)
            db.add(binding)
        else:
            before = {"stripe_price_id": binding.stripe_price_id,
                      "stripe_product_id": binding.stripe_product_id}
        binding.stripe_product_id = body.stripe_product_id
        binding.stripe_price_id = body.stripe_price_id
        # The binding records the CATALOG amount it was attached against, so
        # a later catalog edit shows up as drift instead of silently selling
        # at the old Stripe price.
        binding.price_usd_cents = product["price_usd_cents"]
        binding.interval = product.get("interval")
        _audit(db, request, admin, action="pricing.stripe_binding.upsert",
               target=f"binding:{'live' if s.stripe_livemode else 'test'}:{product_key}",
               reason=reason, before=before,
               after={"stripe_price_id": body.stripe_price_id,
                      "stripe_product_id": body.stripe_product_id,
                      "price_usd_cents": binding.price_usd_cents})
        await db.commit()
        return {"product_key": product_key, "stripe_price_id": binding.stripe_price_id}


class SyncBody(BaseModel):
    reason: str = Field(default="")


@router.post("/stripe-bindings/sync")
async def sync_stripe_bindings(body: SyncBody, request: Request,
                               admin: User = Depends(require_admin)):
    """Pull Prices from Stripe by the 006 lookup-key convention and bind
    every catalog product whose amount and interval match exactly."""
    reason = _require_reason(body.reason)
    s = get_settings()
    gw = StripeGateway.from_settings(s)
    if gw is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Stripe is not configured")
    try:
        async with get_db_session() as db:
            config = await _default_config(db)
            products = config.get("products") or []
            lookup_keys = [_stripe_lookup_key(p) for p in products]
            try:
                resp = await gw.get("/v1/prices", params={
                    "lookup_keys": lookup_keys, "limit": 100, "active": True,
                })
            except StripeError as exc:
                log.error("stripe price lookup failed: %s", exc)
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Payment provider error")
            prices = {p.get("lookup_key"): p for p in resp.get("data") or []}
            bound, mismatched, missing = [], [], []
            for product in products:
                lookup = _stripe_lookup_key(product)
                price = prices.get(lookup)
                if price is None:
                    missing.append(lookup)
                    continue
                interval = (price.get("recurring") or {}).get("interval")
                if (price.get("unit_amount") != product["price_usd_cents"]
                        or price.get("currency") != "usd"
                        or (interval or None) != (product.get("interval") or None)):
                    mismatched.append({
                        "lookup_key": lookup,
                        "stripe_unit_amount": price.get("unit_amount"),
                        "catalog_usd_cents": product["price_usd_cents"],
                        "stripe_interval": interval,
                        "catalog_interval": product.get("interval"),
                    })
                    continue
                binding = (
                    await db.execute(
                        select(StripePriceBinding).where(
                            StripePriceBinding.livemode == s.stripe_livemode,
                            StripePriceBinding.product_key == product["key"],
                        )
                    )
                ).scalar_one_or_none()
                if binding is None:
                    binding = StripePriceBinding(
                        livemode=s.stripe_livemode, product_key=product["key"],
                        stripe_product_id="", stripe_price_id="", price_usd_cents=0,
                    )
                    db.add(binding)
                prod_ref = price.get("product")
                binding.stripe_product_id = (
                    prod_ref.get("id") if isinstance(prod_ref, dict) else prod_ref
                )
                binding.stripe_price_id = price["id"]
                binding.price_usd_cents = product["price_usd_cents"]
                binding.interval = product.get("interval")
                bound.append(product["key"])
            _audit(db, request, admin, action="pricing.stripe_binding.sync",
                   target=f"bindings:{'live' if s.stripe_livemode else 'test'}",
                   reason=reason,
                   after={"bound": bound, "missing": missing,
                          "mismatched": [m["lookup_key"] for m in mismatched]})
            await db.commit()
            return {
                "bound": bound,
                "missing": missing,
                "mismatched": mismatched,
                "payments_enabled": await payments_enabled_for(db, config, s),
            }
    finally:
        await gw.aclose()


# ── Operations & simulations (039/009) ───────────────────────────────────────

@router.get("/ops")
async def ops_overview(admin: User = Depends(require_admin)):
    """Bounded counters + heartbeats. Cheap enough to render on page load;
    the full invariant replay lives behind /ops/invariants."""
    from cloud.billing import operations as ops_svc
    async with get_db_session() as db:
        return await ops_svc.ops_snapshot(db)


@router.get("/ops/invariants")
async def ops_invariants(admin: User = Depends(require_admin)):
    from cloud.billing import operations as ops_svc
    async with get_db_session() as db:
        return await ops_svc.run_invariants(db)


@router.get("/ops/alerts")
async def ops_alerts(admin: User = Depends(require_admin)):
    from cloud.billing.models import OpsAlert
    async with get_db_session() as db:
        rows = (await db.execute(
            select(OpsAlert).order_by(OpsAlert.last_seen_at.desc())
        )).scalars().all()
        return {"alerts": [{
            "alert_key": a.alert_key,
            "severity": a.severity,
            "message": a.message,
            "status": a.status,
            "value": a.value_json,
            "threshold": a.threshold_json,
            "first_seen_at": a.first_seen_at.isoformat() if a.first_seen_at else None,
            "last_seen_at": a.last_seen_at.isoformat() if a.last_seen_at else None,
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
        } for a in rows]}


@router.post("/ops/alerts/evaluate")
async def ops_alerts_evaluate(request: Request, admin: User = Depends(require_admin)):
    from cloud.billing import operations as ops_svc
    async with get_db_session() as db:
        active = await ops_svc.evaluate_alerts(db)
        _audit(db, request, admin, action="pricing.ops.alerts_evaluate",
               target="ops:alerts", after={"active": [a["alert_key"] for a in active]})
        await db.commit()
        return {"active": active}


def _sim_out(sim, *, with_result: bool = False) -> dict:
    manifest = sim.manifest or {}
    out = {
        "id": str(sim.id),
        "state": sim.state,
        "filters": sim.filters,
        "baseline_version_id": str(sim.baseline_version_id) if sim.baseline_version_id else None,
        "candidate_version_id": str(sim.candidate_version_id) if sim.candidate_version_id else None,
        "provider_cost_basis": sim.provider_cost_basis,
        "transforms": sim.transforms,
        "replay_mode": manifest.get("replay_mode"),
        "funding_mode": manifest.get("funding_mode"),
        "event_count": manifest.get("event_count"),
        "config_hash": sim.config_hash,
        "created_at": sim.created_at.isoformat() if sim.created_at else None,
    }
    if with_result:
        out["result"] = sim.result
    elif sim.result is not None:
        out["result_hash"] = sim.result.get("result_hash")
        out["error"] = sim.result.get("error")
    return out


class SimulationRequest(BaseModel):
    filters: dict | None = None
    baseline_version_id: uuid.UUID
    candidate_version_id: uuid.UUID
    provider_cost_basis: str = "original_snapshot"
    provider_cost_version_id: uuid.UUID | None = None
    transforms: dict | None = None
    replay_mode: str = "full_demand"
    funding_mode: str = "actual_grants"


@router.post("/simulations")
async def create_simulation(body: SimulationRequest, request: Request,
                            admin: User = Depends(require_admin)):
    from cloud.billing import simulator as sim_svc
    async with get_db_session() as db:
        try:
            sim = await sim_svc.create_simulation(
                db,
                filters=body.filters,
                baseline_version_id=body.baseline_version_id,
                candidate_version_id=body.candidate_version_id,
                provider_cost_basis=body.provider_cost_basis,
                provider_cost_version_id=body.provider_cost_version_id,
                transforms=body.transforms,
                replay_mode=body.replay_mode,
                funding_mode=body.funding_mode,
                created_by=admin.id,
            )
        except sim_svc.SimulationError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        _audit(db, request, admin, action="pricing.simulation.create",
               target=f"simulation:{sim.id}", after=_sim_out(sim))
        await db.commit()
        return _sim_out(sim)


@router.get("/simulations")
async def list_simulations(admin: User = Depends(require_admin)):
    from cloud.billing.models import PricingSimulation
    async with get_db_session() as db:
        rows = (await db.execute(
            select(PricingSimulation).order_by(PricingSimulation.created_at.desc()).limit(100)
        )).scalars().all()
        return {"simulations": [_sim_out(s) for s in rows]}


async def _sim_or_404(db, simulation_id: uuid.UUID):
    from cloud.billing.models import PricingSimulation
    sim = await db.get(PricingSimulation, simulation_id)
    if sim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Simulation not found")
    return sim


@router.get("/simulations/{simulation_id}")
async def get_simulation(simulation_id: uuid.UUID, admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        sim = await _sim_or_404(db, simulation_id)
        return _sim_out(sim, with_result=True)


@router.get("/simulations/{simulation_id}/csv")
async def simulation_csv(simulation_id: uuid.UUID, admin: User = Depends(require_admin)):
    from fastapi.responses import PlainTextResponse
    from cloud.billing import simulator as sim_svc
    async with get_db_session() as db:
        sim = await _sim_or_404(db, simulation_id)
        if sim.state != "succeeded" or sim.result is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Simulation has no result")
        return PlainTextResponse(
            sim_svc.result_csv(sim), media_type="text/csv",
            headers={"Content-Disposition":
                     f'attachment; filename="simulation-{sim.id}.csv"'},
        )


@router.post("/simulations/{simulation_id}/rerun")
async def rerun_simulation(simulation_id: uuid.UUID, request: Request,
                           admin: User = Depends(require_admin)):
    """Rerun the stored manifest verbatim — the reproducibility path. Late
    events or edited drafts can never change the result."""
    from cloud.billing import simulator as sim_svc
    async with get_db_session() as db:
        sim = await _sim_or_404(db, simulation_id)
        if not sim.manifest:
            raise HTTPException(status.HTTP_409_CONFLICT, "Simulation has no manifest")
        rerun = await sim_svc.create_simulation(db, manifest=sim.manifest,
                                                created_by=admin.id)
        _audit(db, request, admin, action="pricing.simulation.rerun",
               target=f"simulation:{sim.id}", after={"rerun_id": str(rerun.id)})
        await db.commit()
        return _sim_out(rerun)


@router.post("/simulations/{simulation_id}/cancel")
async def cancel_simulation(simulation_id: uuid.UUID, request: Request,
                            admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        sim = await _sim_or_404(db, simulation_id)
        if sim.state in ("succeeded", "failed"):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Simulation already {sim.state}")
        before = {"state": sim.state}
        sim.state = "cancelled"
        _audit(db, request, admin, action="pricing.simulation.cancel",
               target=f"simulation:{sim.id}", before=before,
               after={"state": "cancelled"})
        await db.commit()
        return _sim_out(sim)
