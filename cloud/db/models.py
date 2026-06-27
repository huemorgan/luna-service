"""SQLAlchemy models for the control-plane database."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    google_sub: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    memberships: Mapped[list[Membership]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="free")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    memberships: Mapped[list[Membership]] = relationship(back_populates="account", cascade="all, delete-orphan")
    agents: Mapped[list[Agent]] = relationship(back_populates="account", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("account_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text, nullable=False, default="owner")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    account: Mapped[Account] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"))
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False, default="My Luna")
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    runtime_kind: Mapped[str | None] = mapped_column(Text)
    runtime_ref: Mapped[str | None] = mapped_column(Text)
    internal_url: Mapped[str | None] = mapped_column(Text)
    db_schema: Mapped[str | None] = mapped_column(Text)
    vault_key_ref: Mapped[str | None] = mapped_column(Text)
    # Plan 025.5: per-agent persistent Fly volume backing plugin-files.
    volume_id: Mapped[str | None] = mapped_column(Text)
    volume_region: Mapped[str | None] = mapped_column(Text)
    volume_size_gb: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    image_version: Mapped[str | None] = mapped_column(Text)
    cached_metrics: Mapped[dict | None] = mapped_column(JSONB)
    cached_metrics_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Plan 016: per-agent overrides on top of LunaImage.image_config. Same
    # nested shape as image_config (e.g. {"services": {"composio": {...}}}).
    # NULL means "inherit everything from the image".
    config_overrides: Mapped[dict | None] = mapped_column(JSONB)

    account: Mapped[Account] = relationship(back_populates="agents")


class LunaImage(Base):
    __tablename__ = "luna_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    version: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    registry_tag: Mapped[str] = mapped_column(Text, nullable=False)
    is_main: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    build_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    build_run_id: Mapped[str | None] = mapped_column(Text)
    build_error: Mapped[str | None] = mapped_column(Text)
    git_sha: Mapped[str | None] = mapped_column(Text)
    # Luna git branch this image was built from ("main" for releases; a feature
    # branch for experimental builds). NULL = legacy/main.
    git_branch: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    image_config: Mapped[dict | None] = mapped_column(JSONB)
    cache_warmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 024: upgrade-preview contract. `sdk_major`/`sdk_min_major` are the target
    # band passed to a tenant's /api/plugins/upgrade-check; `release_notes` is a
    # succinct changelog captured at build time. All best-effort/nullable.
    sdk_major: Mapped[int | None] = mapped_column(Integer)
    sdk_min_major: Mapped[int | None] = mapped_column(Integer)
    release_notes: Mapped[str | None] = mapped_column(Text)


class GatewayService(Base):
    """Registry of external keyed services the credential gateway can proxy.

    Adding a service is a data operation — the proxy route, key pool, and
    provisioning all key off these rows.
    """

    __tablename__ = "gateway_services"

    slug: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    upstream_url: Mapped[str] = mapped_column(Text, nullable=False)
    # "header:x-api-key" or "header:Authorization:Bearer"
    auth_style: Mapped[str] = mapped_column(Text, nullable=False)
    luna_credential_name: Mapped[str] = mapped_column(Text, nullable=False)
    luna_env_key_var: Mapped[str] = mapped_column(Text, nullable=False)
    luna_env_base_url_var: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    provision_by_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class GatewayModel(Base):
    """Plan 018 — the system model catalog injected into tenants as
    LUNA_MODEL_CATALOG. One row per supported model. `enabled` = in/out of the
    catalog (selectable). Shape mirrors Luna's ModelCatalogEntry.
    """

    __tablename__ = "gateway_models"
    __table_args__ = (UniqueConstraint("provider", "model"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    context_window: Mapped[int | None] = mapped_column(Integer)
    # purposes this model may serve: reasoning | summarization | embedding.
    # JSONB list (not pg ARRAY) so the same model works on the SQLite test engine;
    # membership checks happen in Python, never in SQL.
    kinds: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    tier: Mapped[str | None] = mapped_column(Text)
    input_cost: Mapped[float | None] = mapped_column(Float)
    output_cost: Mapped[float | None] = mapped_column(Float)
    recommended_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class GatewayKey(Base):
    """Pool of real provider keys. Two scopes: 'global' or 'agent:<agent_id>'.

    Resolution: agent-scoped first, then global, priority ascending within
    each scope. Keys on cooldown are skipped.
    """

    __tablename__ = "gateway_keys"
    __table_args__ = (
        UniqueConstraint("service_slug", "scope", "priority"),
        Index("ix_gateway_keys_service_scope", "service_slug", "scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    service_slug: Mapped[str] = mapped_column(Text, ForeignKey("gateway_services.slug", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="global")
    priority: Mapped[int] = mapped_column(nullable=False, default=1)
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False)  # AES-GCM, base64
    label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class GatewayTenantToken(Base):
    """Tenant tokens (lsv1-…) injected into machines. Hash at rest only."""

    __tablename__ = "gateway_tenant_tokens"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)  # sha256 hex
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageEvent(Base):
    """One row per proxied request. billable=False for BYOK passthrough."""

    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_events_agent_created", "agent_id", "created_at"),
        Index("ix_usage_events_service_created", "service_slug", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"))
    service_slug: Mapped[str] = mapped_column(Text, nullable=False)
    billable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    key_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status_code: Mapped[int | None] = mapped_column()
    request_count: Mapped[int] = mapped_column(nullable=False, default=1)
    input_tokens: Mapped[int | None] = mapped_column()
    output_tokens: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ComposioAccountLink(Base):
    """connected_account_id → agent routing for the trigger relay (plan 015).

    Rows are captured from gateway responses (source='gateway') or entered
    by an admin (source='admin'). The relay routes ONLY from this table —
    never from labels inside a webhook payload.
    """

    __tablename__ = "composio_account_links"

    connected_account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    app_name: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="gateway")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RelayDelivery(Base):
    """Outbox row per accepted Composio webhook delivery (plan 015)."""

    __tablename__ = "relay_deliveries"
    __table_args__ = (
        Index("ix_relay_deliveries_status_next", "status", "next_attempt_at"),
        Index("ix_relay_deliveries_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    webhook_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    connected_account_id: Mapped[str | None] = mapped_column(Text)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL")
    )
    # pending | delivered | dead | unroutable
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column()
    last_error: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)  # raw JSON payload (≤200 KB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_account_id", "account_id"),
        Index("ix_audit_log_action", "action"),
        Index("ix_audit_log_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    actor_ip: Mapped[str | None] = mapped_column(Text)
    before_state: Mapped[dict | None] = mapped_column(JSONB)
    after_state: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AppSetting(Base):
    """Generic singleton key/value store for control-plane settings (Plan 020).

    Currently holds the admin-editable image defaults under key
    ``image_defaults`` (default model + default plugin set). Reused for future
    global singletons rather than one column per setting.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
