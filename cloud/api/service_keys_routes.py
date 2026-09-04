"""Admin API-key management (plan 088).

Cookie-authenticated and same-origin guarded ONLY — a service key can never
mint, list, or revoke keys. The clear secret appears exactly once, in the
create response. No delete: revoked rows stay for audit.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from cloud.auth.api_keys import KNOWN_SCOPES, generate_key, key_state
from cloud.auth.deps import enforce_same_origin, require_admin
from cloud.db import session as db_session
from cloud.db.models import AuditLog, ServiceApiKey, User

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/service-keys",
    tags=["service-keys"],
    dependencies=[Depends(enforce_same_origin)],
)


class CreateKeyBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[str] = Field(min_length=1)
    expires_at: datetime | None = None


def _key_row(k: ServiceApiKey) -> dict:
    return {
        "id": str(k.id),
        "name": k.name,
        "key_prefix": k.key_prefix,
        "scopes": list(k.scopes or []),
        "state": key_state(k),
        "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        "created_at": k.created_at.isoformat() if k.created_at else None,
        "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "created_by": str(k.created_by) if k.created_by else None,
    }


@router.get("/scopes")
async def list_scopes(admin: User = Depends(require_admin)):
    """Checkbox catalog for the admin UI."""
    return {"scopes": [{"scope": s, "label": lbl} for s, lbl in KNOWN_SCOPES.items()]}


@router.get("")
@router.get("/", include_in_schema=False)
async def list_keys(admin: User = Depends(require_admin)):
    async with db_session.get_session() as db:
        rows = (await db.execute(
            select(ServiceApiKey).order_by(ServiceApiKey.created_at.desc())
        )).scalars().all()
    return {"keys": [_key_row(k) for k in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_key(payload: CreateKeyBody, admin: User = Depends(require_admin)):
    unknown = [s for s in payload.scopes if s not in KNOWN_SCOPES]
    if unknown:
        raise HTTPException(422, f"Unknown scopes: {', '.join(unknown)}")
    expires_at = payload.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(422, "expires_at must be in the future")
    secret, key_hash, prefix = generate_key()
    async with db_session.get_session() as db:
        key = ServiceApiKey(
            name=payload.name.strip(),
            key_hash=key_hash,
            key_prefix=prefix,
            scopes=sorted(set(payload.scopes)),
            expires_at=expires_at,
            created_by=admin.id,
        )
        db.add(key)
        db.add(AuditLog(
            actor_user_id=admin.id,
            action="service_key.create",
            target=key.name,
            metadata_={"scopes": key.scopes, "expires_at":
                       expires_at.isoformat() if expires_at else None},
        ))
        await db.flush()
        row = _key_row(key)
        await db.commit()
    log.info("service_key.created", extra={"name": row["name"], "scopes": row["scopes"]})
    return {**row, "key": secret}


@router.post("/{key_id}/revoke")
async def revoke_key(key_id: str, admin: User = Depends(require_admin)):
    try:
        kid = uuid.UUID(key_id)
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    async with db_session.get_session() as db:
        key = (await db.execute(
            select(ServiceApiKey).where(ServiceApiKey.id == kid)
        )).scalar_one_or_none()
        if not key:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
        if key.revoked_at is None:
            key.revoked_at = datetime.now(timezone.utc)
            db.add(AuditLog(
                actor_user_id=admin.id,
                action="service_key.revoke",
                target=key.name,
            ))
            await db.commit()
        row = _key_row(key)
    return row
