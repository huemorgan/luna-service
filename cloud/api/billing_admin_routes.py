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
from cloud.billing import modes as modes_svc
from cloud.billing import versions as versions_svc
from cloud.billing.models import (
    AccountBalanceProjection,
    BillingAccount,
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
        from cloud.billing import operations as ops
        payments_granted_nothing = (await ops._payments_granted_nothing(db))["count"]
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
            "payments_granted_nothing": payments_granted_nothing,
            "needs_reconciliation_holds": reconciliation_holds,
            "assigned_accounts": assigned_accounts,
        }


@router.get("/billing-jobs")
async def list_billing_jobs(
    status_filter: str | None = None, limit: int = 50,
    admin: User = Depends(require_admin),
):
    """Inspect outbox jobs with full detail (payload / result / last_error) so
    a failed money-in grant can be diagnosed from the admin API without direct
    DB access. `status` filters to one outbox status; unset returns the
    attention set — dead jobs plus money-in jobs that granted nothing (047)."""
    limit = max(1, min(limit, 200))
    from cloud.billing.operations import MONEY_IN_JOB_TYPES
    async with get_db_session() as db:
        stmt = select(BillingJob)
        if status_filter:
            stmt = stmt.where(BillingJob.status == status_filter)
        else:
            # Attention set: dead jobs, plus money-in jobs that succeeded but
            # granted nothing. The "granted" flag lives in a JSONB column, so
            # filter that predicate in Python (portable across SQLite tests).
            stmt = stmt.where(
                (BillingJob.status == "dead")
                | (
                    BillingJob.job_type.in_(MONEY_IN_JOB_TYPES)
                    & (BillingJob.status == "succeeded")
                )
            )
        rows = (
            await db.execute(stmt.order_by(BillingJob.updated_at.desc()).limit(limit * 2))
        ).scalars().all()
        jobs = []
        for j in rows:
            if (
                not status_filter
                and j.status == "succeeded"
                and isinstance(j.result, dict)
                and j.result.get("granted")
            ):
                continue  # a real grant is not an anomaly
            jobs.append(j)
            if len(jobs) >= limit:
                break
        return {
            "jobs": [
                {
                    "id": str(j.id),
                    "job_type": j.job_type,
                    "status": j.status,
                    "attempts": j.attempts,
                    "max_attempts": j.max_attempts,
                    "dedupe_key": j.dedupe_key,
                    "payload": j.payload,
                    "result": j.result,
                    "last_error": j.last_error,
                    "next_attempt_at": j.next_attempt_at.isoformat() if j.next_attempt_at else None,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                    "updated_at": j.updated_at.isoformat() if j.updated_at else None,
                }
                for j in jobs
            ],
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


# ── Enforcement overrides (039/010) ──────────────────────────────────────────
# Per-account/cohort escalation over the global CLOUD_BILLING_MODE. The
# effective mode is max(global, override), so an override can only escalate —
# internal canaries get enforced without touching customers.

class OverrideRequest(BaseModel):
    account_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    mode: str | None = None  # observe | shadow | enforce; None clears
    reason: str = Field(default="")


@router.get("/enforcement")
async def enforcement_state(admin: User = Depends(require_admin)):
    from cloud.billing import hosting as billing_hosting

    async with get_db_session() as db:
        rows = (
            await db.execute(
                select(BillingAccount, Account)
                .join(Account, Account.id == BillingAccount.account_id)
                .where(BillingAccount.enforcement_override.is_not(None))
                .order_by(BillingAccount.enforcement_override_set_at.desc())
            )
        ).all()
        return {
            "global_mode": billing_hosting.billing_mode(),
            "modes": list(modes_svc.MODES),
            "overrides": [
                {
                    "account_id": str(ba.account_id),
                    "slug": acc.slug,
                    "name": acc.name,
                    "mode": ba.enforcement_override,
                    "effective_mode": modes_svc.combine(
                        billing_hosting.billing_mode(), ba.enforcement_override
                    ),
                    "set_at": ba.enforcement_override_set_at.isoformat()
                    if ba.enforcement_override_set_at else None,
                }
                for ba, acc in rows
            ],
        }


@router.post("/enforcement/overrides")
async def set_enforcement_overrides(body: OverrideRequest, request: Request,
                                    admin: User = Depends(require_admin)):
    if body.mode is not None and body.mode not in modes_svc.OVERRIDE_MODES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"mode must be one of {list(modes_svc.OVERRIDE_MODES)} or null")
    reason = _require_reason(body.reason)
    async with get_db_session() as db:
        applied = []
        for account_id in body.account_ids:
            account = await db.get(Account, account_id)
            if account is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND,
                                    f"Account not found: {account_id}")
            before = await modes_svc.account_override(db, account_id)
            await modes_svc.set_override(db, account_id, body.mode)
            _audit(db, request, admin, action="pricing.enforcement.override",
                   target=f"account:{account_id}", reason=reason,
                   before={"mode": before}, after={"mode": body.mode})
            applied.append({"account_id": str(account_id), "slug": account.slug,
                            "mode": body.mode})
        await db.commit()
    return {"applied": applied}


@router.get("/accounts/search")
async def search_accounts(q: str = "", admin: User = Depends(require_admin)):
    """Account picker for the enforcement UI: match slug or name."""
    async with get_db_session() as db:
        query = (
            select(Account, BillingAccount.enforcement_override,
                   BillingAccount.active_luna_cap_override)
            .join(BillingAccount, BillingAccount.account_id == Account.id, isouter=True)
            .order_by(Account.created_at.desc())
            .limit(20)
        )
        term = q.strip()
        if term:
            like = f"%{term}%"
            query = query.where(Account.slug.ilike(like) | Account.name.ilike(like))
        rows = (await db.execute(query)).all()
        return {
            "accounts": [
                {"id": str(acc.id), "slug": acc.slug, "name": acc.name,
                 "override": override, "active_luna_cap_override": cap_override}
                for acc, override, cap_override in rows
            ]
        }


# ── Per-account limits (057) ─────────────────────────────────────────────────

class AccountLimitsRequest(BaseModel):
    active_luna_cap: int | None = Field(default=None, ge=1)
    reason: str = Field(default="")


@router.post("/accounts/{account_id}/limits")
async def set_account_limits(account_id: uuid.UUID, body: AccountLimitsRequest,
                             request: Request, admin: User = Depends(require_admin)):
    """Set/clear the per-account active-Luna cap override (null = pricing
    default). Never touches metering — agents still burn hosting + usage."""
    reason = _require_reason(body.reason)
    async with get_db_session() as db:
        account = await db.get(Account, account_id)
        if account is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
        from cloud.billing.ledger import ensure_billing_account
        ba = await ensure_billing_account(db, account_id)
        before = {"active_luna_cap_override": ba.active_luna_cap_override}
        ba.active_luna_cap_override = body.active_luna_cap
        _audit(db, request, admin, action="pricing.account_limits.set",
               target=f"account:{account_id}", reason=reason, before=before,
               after={"active_luna_cap_override": body.active_luna_cap})
        await db.commit()
        return {"account_id": str(account_id),
                "active_luna_cap_override": ba.active_luna_cap_override}


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


# ── Cost benchmark (plan 040) ─────────────────────────────────────────────────

from cloud.billing import benchmark as benchmark_svc  # noqa: E402
from cloud.billing import benchmark_profiles as bprofiles  # noqa: E402
from cloud.billing import benchmark_playbook as bplaybook  # noqa: E402
from cloud.billing.models import BenchmarkRun, BenchmarkStep, BenchmarkStepEvent  # noqa: E402
from cloud.db.models import Agent  # noqa: E402


def _run_dict(run: BenchmarkRun, agent_slug: str | None = None) -> dict:
    return {
        "id": str(run.id),
        "agent_id": str(run.agent_id),
        "agent_slug": agent_slug,
        "account_id": str(run.account_id),
        "image_version": run.image_version,
        "playbook_version": run.playbook_version,
        "item_keys": run.item_keys,
        "repetitions": run.repetitions,
        "state": run.state,
        "progress": run.progress,
        "totals": run.totals,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _step_dict(s: BenchmarkStep) -> dict:
    return {
        "id": str(s.id), "seq": s.seq, "item_key": s.item_key,
        "repetition": s.repetition, "status": s.status,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        "latency_ms": s.latency_ms, "llm_requests": s.llm_requests,
        "input_tokens": s.input_tokens, "output_tokens": s.output_tokens,
        "cache_read_tokens": s.cache_read_tokens,
        "cache_write_tokens": s.cache_write_tokens,
        "per_model": s.per_model, "credits": s.credits,
        "vendor_cost_micro_usd": s.vendor_cost_micro_usd,
        "margin_micro_usd": s.margin_micro_usd, "error": s.error,
    }


def _event_dict(e: BenchmarkStepEvent) -> dict:
    return {
        "id": str(e.id), "step_id": str(e.step_id),
        "billable_event_id": str(e.billable_event_id) if e.billable_event_id else None,
        "ts": e.ts.isoformat() if e.ts else None,
        "call_id": e.call_id, "service": e.service, "sku": e.sku,
        "provider": e.provider, "model": e.model,
        "attempt_number": e.attempt_number, "quantities": e.quantities,
        "vendor_cost_micro_usd": e.vendor_cost_micro_usd,
        "credits": e.credits, "cost_source": e.cost_source,
    }


@router.get("/benchmark/playbook")
async def benchmark_playbook(admin: User = Depends(require_admin)):
    return {
        "playbook_version": bplaybook.PLAYBOOK_VERSION,
        "items": [
            {"key": i.key, "title": i.title, "category": i.category,
             "kind": i.kind, "smoke": i.smoke,
             "default_included": i.default_included,
             "plugins": list(i.plugins), "notes": i.notes,
             "window_seconds": i.window_seconds}
            for i in bplaybook.CATALOG
        ],
        "smoke_keys": list(bplaybook.SMOKE_KEYS),
        "default_keys": list(bplaybook.DEFAULT_KEYS),
        "coverage": bplaybook.coverage(),
        "uncovered_plugins": bplaybook.uncovered_plugins(),
        "presets": bprofiles.PRESET_PROFILES,
    }


@router.get("/benchmark/targets")
async def benchmark_targets(admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        agents = (await db.execute(
            select(Agent).where(Agent.deleted_at.is_(None)).order_by(Agent.created_at.desc())
        )).scalars().all()
        return {
            "targets": [
                {"id": str(a.id), "slug": a.slug, "name": a.name, "status": a.status}
                for a in agents if benchmark_svc.is_benchmark_target(a)
            ]
        }


class TargetFlagRequest(BaseModel):
    target: bool
    reason: str = ""


@router.post("/benchmark/targets/{agent_id}")
async def set_benchmark_target(agent_id: uuid.UUID, body: TargetFlagRequest,
                               request: Request, admin: User = Depends(require_admin)):
    reason = _require_reason(body.reason)
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        overrides = dict(agent.config_overrides or {})
        before = bool((overrides.get("benchmark") or {}).get("target"))
        bench = dict(overrides.get("benchmark") or {})
        bench["target"] = body.target
        overrides["benchmark"] = bench
        agent.config_overrides = overrides
        _audit(db, request, admin, action="pricing.benchmark.target",
               target=f"agent:{agent.slug}", reason=reason,
               before={"target": before}, after={"target": body.target})
        await db.commit()
    return {"agent_id": str(agent_id), "target": body.target}


class BenchmarkRunRequest(BaseModel):
    agent_id: uuid.UUID
    item_keys: list[str] | None = None
    repetitions: int = Field(default=3, ge=1, le=10)
    smoke: bool = False
    reason: str = ""


@router.post("/benchmark/runs", status_code=status.HTTP_201_CREATED)
async def start_benchmark_run(body: BenchmarkRunRequest, request: Request,
                              admin: User = Depends(require_admin)):
    reason = _require_reason(body.reason)
    keys = body.item_keys
    if keys is None and body.smoke:
        keys = list(bplaybook.SMOKE_KEYS)
    async with get_db_session() as db:
        agent = await db.get(Agent, body.agent_id)
        if agent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        try:
            run = await benchmark_svc.start_run(
                db, agent=agent, created_by=admin.id,
                item_keys=keys, repetitions=body.repetitions,
            )
        except benchmark_svc.BenchmarkError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        _audit(db, request, admin, action="pricing.benchmark.run.started",
               target=f"agent:{agent.slug}", reason=reason,
               after={"run_id": str(run.id), "items": len(run.item_keys),
                      "repetitions": run.repetitions})
        await db.commit()
        return _run_dict(run, agent.slug)


@router.get("/benchmark/runs")
async def list_benchmark_runs(limit: int = 25, admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        rows = (await db.execute(
            select(BenchmarkRun, Agent.slug)
            .join(Agent, Agent.id == BenchmarkRun.agent_id)
            .order_by(BenchmarkRun.created_at.desc())
            .limit(min(max(limit, 1), 100))
        )).all()
        return {"runs": [_run_dict(run, slug) for run, slug in rows]}


async def _get_run(db, run_id: uuid.UUID) -> BenchmarkRun:
    run = await db.get(BenchmarkRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return run


@router.get("/benchmark/runs/{run_id}")
async def get_benchmark_run(run_id: uuid.UUID, admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        run = await _get_run(db, run_id)
        agent = await db.get(Agent, run.agent_id)
        steps = (await db.execute(
            select(BenchmarkStep).where(BenchmarkStep.run_id == run.id)
            .order_by(BenchmarkStep.seq.asc())
        )).scalars().all()
        d = _run_dict(run, agent.slug if agent else None)
        d["steps"] = [_step_dict(s) for s in steps]
        d["medians"] = bprofiles.item_medians(steps)
        d["averages"] = bprofiles.item_stats(steps)
        return d


@router.get("/benchmark/runs/{run_id}/events")
async def get_benchmark_events(run_id: uuid.UUID, step_id: uuid.UUID | None = None,
                               limit: int = 500, offset: int = 0,
                               admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        await _get_run(db, run_id)
        q = (select(BenchmarkStepEvent)
             .where(BenchmarkStepEvent.run_id == run_id)
             .order_by(BenchmarkStepEvent.ts.asc())
             .limit(min(max(limit, 1), 2000)).offset(max(offset, 0)))
        if step_id is not None:
            q = q.where(BenchmarkStepEvent.step_id == step_id)
        events = (await db.execute(q)).scalars().all()
        return {"events": [_event_dict(e) for e in events]}


@router.get("/benchmark/runs/{run_id}/export")
async def export_benchmark_run(run_id: uuid.UUID, admin: User = Depends(require_admin)):
    """The full run — aggregates plus the complete trigger log — as one JSON
    document for offline optimization analysis."""
    async with get_db_session() as db:
        run = await _get_run(db, run_id)
        agent = await db.get(Agent, run.agent_id)
        steps = (await db.execute(
            select(BenchmarkStep).where(BenchmarkStep.run_id == run.id)
            .order_by(BenchmarkStep.seq.asc())
        )).scalars().all()
        events = (await db.execute(
            select(BenchmarkStepEvent).where(BenchmarkStepEvent.run_id == run.id)
            .order_by(BenchmarkStepEvent.ts.asc())
        )).scalars().all()
        by_step: dict[str, list[dict]] = {}
        for e in events:
            by_step.setdefault(str(e.step_id), []).append(_event_dict(e))
        d = _run_dict(run, agent.slug if agent else None)
        d["steps"] = [{**_step_dict(s), "events": by_step.get(str(s.id), [])} for s in steps]
        d["medians"] = bprofiles.item_medians(steps)
        d["averages"] = bprofiles.item_stats(steps)
        return d


@router.post("/benchmark/runs/{run_id}/abort")
async def abort_benchmark_run(run_id: uuid.UUID, request: Request,
                              admin: User = Depends(require_admin)):
    async with get_db_session() as db:
        run = await _get_run(db, run_id)
        if run.state in ("succeeded", "failed", "aborted"):
            return {"state": run.state}
        before = run.state
        run.state = "aborted"
        run.finished_at = datetime.now(timezone.utc)
        _audit(db, request, admin, action="pricing.benchmark.run.aborted",
               target=f"run:{run_id}", before={"state": before},
               after={"state": "aborted"})
        await db.commit()
        return {"state": "aborted"}


class ProjectionRequest(BaseModel):
    run_id: uuid.UUID
    preset: str | None = None
    profile: dict[str, int] | None = None
    hosting_credits: int = Field(default=999, ge=0)


@router.post("/benchmark/projection")
async def benchmark_projection(body: ProjectionRequest, admin: User = Depends(require_admin)):
    profile = body.profile
    if profile is None:
        if body.preset not in bprofiles.PRESET_PROFILES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"preset must be one of {list(bprofiles.PRESET_PROFILES)}")
        profile = bprofiles.PRESET_PROFILES[body.preset]
    async with get_db_session() as db:
        run = await _get_run(db, body.run_id)
        steps = (await db.execute(
            select(BenchmarkStep).where(BenchmarkStep.run_id == run.id)
        )).scalars().all()
        return bprofiles.project(steps, profile, hosting_credits=body.hosting_credits)
