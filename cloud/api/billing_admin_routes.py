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
)
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
