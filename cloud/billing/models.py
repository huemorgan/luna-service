"""Plan 039/001 — billing schema.

Shares the control-plane `Base` so the test harness creates these tables, but
production schema comes exclusively from Alembic migrations (0002+), never
from `create_all`.

Conventions:
- credits are signed BigInteger (1 credit = $0.01); micro-USD are BigInteger.
- Financial FKs to `accounts`/`agents` use ondelete=RESTRICT — attribution
  history can never be erased by deleting an account or agent.
- Exact non-integer provider rates are rationals: (numerator, denominator).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloud.db.models import Base, _new_uuid, _utcnow

# BigInteger everywhere except SQLite, whose autoincrement needs INTEGER.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


# ── Pricing versions ─────────────────────────────────────────────────────────

class CommercialPricingVersion(Base):
    """Immutable, account-assigned commercial pricing snapshot."""

    __tablename__ = "commercial_pricing_versions"
    __table_args__ = (
        CheckConstraint("status IN ('draft','published','retired')", name="ck_cpv_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    version_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commercial_pricing_versions.id", ondelete="RESTRICT")
    )
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    config_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommercialPricingAssignment(Base):
    """Which commercial version governs an account over a time interval.

    Intervals for one account never overlap (service-enforced under the
    billing-account row lock).
    """

    __tablename__ = "commercial_pricing_assignments"
    __table_args__ = (
        Index("ix_cpa_account_effective", "account_id", "effective_at"),
        CheckConstraint(
            "source IN ('new_account_default','global_rollout','manual_test','migration')",
            name="ck_cpa_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    commercial_pricing_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commercial_pricing_versions.id", ondelete="RESTRICT"), nullable=False
    )
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    audit_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class CommercialPricingRollout(Base):
    __tablename__ = "commercial_pricing_rollouts"
    __table_args__ = (
        CheckConstraint(
            "audience IN ('new_accounts','all_accounts','selected_accounts')",
            name="ck_cpr_audience",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    commercial_pricing_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commercial_pricing_versions.id", ondelete="RESTRICT"), nullable=False
    )
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    selected_account_ids: Mapped[list | None] = mapped_column(JSONB)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    migration_policy: Mapped[str] = mapped_column(Text, nullable=False, default="next_renewal")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="scheduled")
    accounts_scheduled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accounts_applied: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accounts_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ProviderCostVersion(Base):
    """Globally effective-dated snapshot of Luna's real provider tariffs."""

    __tablename__ = "provider_cost_versions"
    __table_args__ = (
        CheckConstraint("status IN ('draft','published','retired')", name="ck_pcv_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    version_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderCostRate(Base):
    """One exact rational micro-USD rate per (provider, sku, dimension)."""

    __tablename__ = "provider_cost_rates"
    __table_args__ = (
        UniqueConstraint("provider_cost_version_id", "provider", "sku", "dimension"),
        CheckConstraint("rate_denominator > 0", name="ck_pcr_denominator"),
        CheckConstraint("rate_numerator >= 0", name="ck_pcr_numerator"),
        CheckConstraint(
            "quality IN ('estimated','provider_confirmed','reconciled')", name="ck_pcr_quality"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    provider_cost_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_cost_versions.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    sku: Mapped[str] = mapped_column(Text, nullable=False)  # canonical model or service SKU
    region_tier: Mapped[str | None] = mapped_column(Text)
    dimension: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. input_tokens
    unit: Mapped[str] = mapped_column(Text, nullable=False)  # native unit, e.g. "token"
    rate_numerator: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rate_denominator: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    quality: Mapped[str] = mapped_column(Text, nullable=False, default="estimated")
    source_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ── Wallet and grants ────────────────────────────────────────────────────────

class BillingAccount(Base):
    """One row per Account. The row lock on this table serializes all
    financial mutations for the account."""

    __tablename__ = "billing_accounts"
    __table_args__ = (
        CheckConstraint(
            "enforcement_override IN ('observe','shadow','enforce')",
            name="ck_billing_account_override",
        ),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), primary_key=True
    )
    billing_status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    # 039/010 rollout: per-account escalation over the global CLOUD_BILLING_MODE
    # (effective mode = max of the two; see cloud/billing/modes.py).
    enforcement_override: Mapped[str | None] = mapped_column(Text)
    enforcement_override_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commercial_pricing_assignments.id", ondelete="RESTRICT")
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(Text, unique=True)
    auto_topup: Mapped[dict | None] = mapped_column(JSONB)
    overrun_cap_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class CreditGrant(Base):
    """A grant lot. `remaining_credits` only ever decreases via consumption,
    expiration, or reversal, and is never negative."""

    __tablename__ = "credit_grants"
    __table_args__ = (
        UniqueConstraint("source_key"),
        Index("ix_credit_grants_account_status", "account_id", "status"),
        CheckConstraint("remaining_credits >= 0", name="ck_grant_remaining_nonneg"),
        CheckConstraint("original_credits >= 0", name="ck_grant_original_nonneg"),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_at", name="ck_grant_expiry_window"
        ),
        CheckConstraint(
            "source_type IN ('subscription_paid','subscription_bonus','topup','free_recurring','gift','refund','admin')",
            name="ck_grant_source_type",
        ),
        CheckConstraint(
            "status IN ('scheduled','active','exhausted','expired','reversed')",
            name="ck_grant_status",
        ),
        CheckConstraint(
            "visible_category IN ('bonus','gift','free','paid','topup')",
            name="ck_grant_category",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Idempotent origin, e.g. "stripe:{invoice}:{product}:paid:3" or "trial:{account}".
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remaining_credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    visible_category: Mapped[str] = mapped_column(Text, nullable=False)
    burn_priority: Mapped[int] = mapped_column(Integer, nullable=False)
    stripe_ref: Mapped[str | None] = mapped_column(Text)
    cash_paid_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    grant_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_ledger_transactions.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class CreditLedgerTransaction(Base):
    """Immutable transaction header. `seq` is the monotonic ledger sequence
    used by projections to detect stale writes."""

    __tablename__ = "credit_ledger_transactions"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        Index("ix_clt_account_seq", "account_id", "seq"),
        CheckConstraint(
            "type IN ('grant','charge','expiration','refund','reversal','adjustment','debt_repayment')",
            name="ck_clt_type",
        ),
    )

    seq: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False, default=_new_uuid)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT")
    )
    root_action_id: Mapped[str | None] = mapped_column(Text)
    service: Mapped[str | None] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(Text)
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_ledger_transactions.id", ondelete="RESTRICT")
    )
    commercial_pricing_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commercial_pricing_versions.id", ondelete="RESTRICT")
    )
    provider_cost_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_cost_versions.id", ondelete="RESTRICT")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(Text)
    # Never contains prompts, outputs, credentials, or card data.
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class CreditLedgerPosting(Base):
    """Signed movement on one ledger account. Sum per transaction is zero
    (service-enforced everywhere; trigger-enforced on Postgres)."""

    __tablename__ = "credit_ledger_postings"
    __table_args__ = (
        Index("ix_clp_transaction", "transaction_id"),
        Index("ix_clp_ledger_account", "ledger_account"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_ledger_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    # customer_wallet | grant_issuance:{source} | credits_consumed |
    # uncovered_debt | credits_expired | manual_adjustment
    ledger_account: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class CreditConsumption(Base):
    """Charge transaction → grant lot allocation. A NULL grant_id row is the
    uncovered amount that became debt; `repaid_credits` tracks how much of it
    later debt repayments reallocated."""

    __tablename__ = "credit_consumptions"
    __table_args__ = (
        Index("ix_cc_transaction", "charge_transaction_id"),
        Index("ix_cc_grant", "grant_id"),
        CheckConstraint("credits > 0", name="ck_cc_credits_positive"),
        CheckConstraint("repaid_credits >= 0", name="ck_cc_repaid_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    charge_transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_ledger_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_grants.id", ondelete="RESTRICT")
    )
    credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    repaid_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class AccountBalanceProjection(Base):
    """Rebuildable read model of an account's balances. Never a source of
    truth — always derivable from ledger + grants + holds."""

    __tablename__ = "account_balance_projections"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_accounts.account_id", ondelete="RESTRICT"), primary_key=True
    )
    posted_balance_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bonus_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    gift_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    free_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    paid_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    topup_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    debt_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    open_exposure_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    next_expiry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


# ── Holds, limits, periods ───────────────────────────────────────────────────

class BillingHold(Base):
    __tablename__ = "billing_holds"
    __table_args__ = (
        UniqueConstraint("operation_id"),
        Index("ix_holds_account_status", "account_id", "status"),
        CheckConstraint(
            "status IN ('open','settled','released','expired','needs_reconciliation')",
            name="ck_hold_status",
        ),
        CheckConstraint("estimated_credits >= 0", name="ck_hold_estimate_nonneg"),
        CheckConstraint("overrun_credits >= 0", name="ck_hold_overrun_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    operation_id: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT")
    )
    root_action_id: Mapped[str | None] = mapped_column(Text)
    service: Mapped[str | None] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(Text)
    commercial_pricing_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commercial_pricing_versions.id", ondelete="RESTRICT")
    )
    provider_cost_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_cost_versions.id", ondelete="RESTRICT")
    )
    estimated_credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Portion of the estimate not covered by available balance — the single
    # permitted bounded overrun when > 0.
    overrun_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    settle_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_ledger_transactions.id", ondelete="RESTRICT")
    )
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentCreditLimit(Base):
    __tablename__ = "agent_credit_limits"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), primary_key=True
    )
    daily_limit_credits: Mapped[int | None] = mapped_column(BigInteger)
    monthly_limit_credits: Mapped[int | None] = mapped_column(BigInteger)
    warning_threshold_pct: Mapped[int | None] = mapped_column(Integer)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class AgentLimitPeriod(Base):
    __tablename__ = "agent_limit_periods"
    __table_args__ = (
        UniqueConstraint("agent_id", "period_kind", "period_start"),
        CheckConstraint("period_kind IN ('daily','monthly')", name="ck_alp_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    period_kind: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    open_exposure_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class AgentHostingPeriod(Base):
    __tablename__ = "agent_hosting_periods"
    __table_args__ = (
        UniqueConstraint("agent_id", "starts_at"),
        CheckConstraint(
            "state IN ('pending','paid','active','ended','payment_due','stopped')",
            name="ck_ahp_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    commercial_pricing_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commercial_pricing_versions.id", ondelete="RESTRICT")
    )
    charge_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_ledger_transactions.id", ondelete="RESTRICT")
    )
    resource_allocation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resource_allocations.id", ondelete="RESTRICT")
    )
    state: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


# ── Metering and rating ──────────────────────────────────────────────────────

class BillableEvent(Base):
    """What happened and what Luna actually paid. Never contains prompts,
    completions, tool arguments, credentials, or personal content."""

    __tablename__ = "billable_events"
    __table_args__ = (
        UniqueConstraint("source_idempotency_key"),
        Index("ix_be_account_event_at", "account_id", "event_at"),
        Index("ix_be_call", "call_id"),
        CheckConstraint("context IN ('agent','direct','forge')", name="ck_be_context"),
        CheckConstraint(
            "cost_source IN ('provider_usage','catalog','reconciled','estimated')",
            name="ck_be_cost_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    source_idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    call_id: Mapped[str] = mapped_column(Text, nullable=False)  # logical call / operation ID
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT")
    )
    root_action_id: Mapped[str | None] = mapped_column(Text)
    root_action_type: Mapped[str | None] = mapped_column(Text)  # chat|playbook_run|scheduled_run|background_run|forge_job
    job_id: Mapped[str | None] = mapped_column(Text)
    plugin: Mapped[str | None] = mapped_column(Text)
    service: Mapped[str] = mapped_column(Text, nullable=False)
    sku: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=False)
    model_tier: Mapped[str | None] = mapped_column(Text)  # top|mid, gateway-verified
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    provider_request_id: Mapped[str | None] = mapped_column(Text)
    provider_response_id: Mapped[str | None] = mapped_column(Text)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quantity_json: Mapped[dict | None] = mapped_column(JSONB)
    vendor_cost_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_source: Mapped[str] = mapped_column(Text, nullable=False, default="catalog")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="recorded")
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class RatedCharge(Base):
    """How billable events became one integer credit charge for a logical call."""

    __tablename__ = "rated_charges"
    __table_args__ = (
        UniqueConstraint("logical_call_id"),
        Index("ix_rc_account", "account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    logical_call_id: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    hold_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_holds.id", ondelete="RESTRICT")
    )
    commercial_pricing_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commercial_pricing_versions.id", ondelete="RESTRICT")
    )
    provider_cost_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_cost_versions.id", ondelete="RESTRICT")
    )
    rule_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    vendor_cost_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    margin_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rounding_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Vendor cost Luna absorbed for failed attempts (never charged to customer).
    luna_absorbed_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    charge_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    ledger_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_ledger_transactions.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ResourceAllocation(Base):
    __tablename__ = "resource_allocations"
    __table_args__ = (Index("ix_ra_agent", "agent_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    resource_kind: Mapped[str] = mapped_column(Text, nullable=False)  # machine|volume|...
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    sku: Mapped[str | None] = mapped_column(Text)
    provider_resource_id: Mapped[str | None] = mapped_column(Text)
    dimensions: Mapped[dict | None] = mapped_column(JSONB)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_accrued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconcile_state: Mapped[str] = mapped_column(Text, nullable=False, default="pending")


class UsageRollup(Base):
    __tablename__ = "usage_rollups"
    __table_args__ = (
        UniqueConstraint("day", "account_id", "agent_id", "service", "context", "model"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    day: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # UTC day start
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT")
    )
    service: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str] = mapped_column(Text, nullable=False, default="")
    calls: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    quantities: Mapped[dict | None] = mapped_column(JSONB)
    credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    vendor_cost_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    estimated_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reconciled_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


# ── Durable work and simulations ─────────────────────────────────────────────

class ProcessedWebhook(Base):
    __tablename__ = "processed_webhooks"
    __table_args__ = (UniqueConstraint("provider", "event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    provider: Mapped[str] = mapped_column(Text, nullable=False, default="stripe")
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str | None] = mapped_column(Text)
    object_ids: Mapped[dict | None] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="received")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillingJob(Base):
    """Durable billing outbox/worker job. Claimed with FOR UPDATE SKIP LOCKED
    on Postgres, leased with heartbeats, bounded retries, dead-letter state."""

    __tablename__ = "billing_outbox"
    __table_args__ = (
        Index("ix_bo_claim", "status", "next_attempt_at"),
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed','dead')",
            name="ck_bo_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leased_by: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


# ── Stripe integration (039/007) ─────────────────────────────────────────────

class StripePriceBinding(Base):
    """Catalog product key → Stripe Price, per mode. Bindings gate checkout
    activation; catalog publication (002) is deliberately decoupled from
    Stripe. Amounts are recorded so a drift between the catalog and the
    bound Price is detectable before money moves."""

    __tablename__ = "stripe_price_bindings"
    __table_args__ = (UniqueConstraint("livemode", "product_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    livemode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    product_key: Mapped[str] = mapped_column(Text, nullable=False)
    stripe_product_id: Mapped[str] = mapped_column(Text, nullable=False)
    stripe_price_id: Mapped[str] = mapped_column(Text, nullable=False)
    price_usd_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    interval: Mapped[str | None] = mapped_column(Text)  # month | year | None (one-time)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class StripeSubscription(Base):
    """The account's single Luna Credits subscription (at most one, PK =
    account). A mirror of Stripe state updated only from canonical objects
    retrieved via the API — never from browser redirects. A downgrade lives
    in `pending_product_key` until renewal applies it."""

    __tablename__ = "stripe_subscriptions"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_accounts.account_id", ondelete="RESTRICT"), primary_key=True
    )
    stripe_subscription_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    product_key: Mapped[str] = mapped_column(Text, nullable=False)
    stripe_price_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # Stripe's status verbatim
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pending_product_key: Mapped[str | None] = mapped_column(Text)
    payment_action_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_payment_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class StripePayment(Base):
    """Payment-level clawback accumulator: one row per VERIFIED money-in
    payment (subscription invoice or top-up PaymentIntent). Refunds and
    disputes both accumulate into `refunded_pretax_cents`/`clawed_credits`,
    so the proportional reversal can never double-claw. Amounts are the
    pretax product line — tax and fees map to zero credits."""

    __tablename__ = "stripe_payments"
    __table_args__ = (
        UniqueConstraint("payment_ref"),
        Index("ix_stripe_payments_account", "account_id"),
        CheckConstraint("kind IN ('subscription','topup')", name="ck_sp_kind"),
        CheckConstraint(
            "dispute_status IS NULL OR dispute_status IN ('created','won','lost')",
            name="ck_sp_dispute",
        ),
        CheckConstraint(
            "refunded_pretax_cents >= 0 AND refunded_pretax_cents <= pretax_amount_cents",
            name="ck_sp_refund_bounds",
        ),
        CheckConstraint(
            "disputed_pretax_cents >= 0 AND disputed_pretax_cents <= pretax_amount_cents",
            name="ck_sp_dispute_bounds",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    # "invoice:{id}" for subscription cycles, "pi:{id}" for top-ups.
    payment_ref: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    product_key: Mapped[str] = mapped_column(Text, nullable=False)
    commercial_pricing_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commercial_pricing_versions.id", ondelete="RESTRICT")
    )
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="usd")
    pretax_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    granted_credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refunded_pretax_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Kept separate from refunds so a won dispute releases exactly the
    # disputed portion while real refunds stay clawed.
    disputed_pretax_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    clawed_credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    dispute_status: Mapped[str | None] = mapped_column(Text)
    stripe_charge_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class OpsAlert(Base):
    """One row per alert key (039/009). Active alerts refresh in place; a
    resolved alert re-firing inside its dedupe window reactivates the same
    row instead of counting as a new incident."""

    __tablename__ = "ops_alerts"
    __table_args__ = (
        CheckConstraint("severity IN ('info','warning','critical')", name="ck_oa_severity"),
        CheckConstraint("status IN ('active','resolved')", name="ck_oa_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    alert_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    value_json: Mapped[dict | None] = mapped_column(JSONB)
    threshold_json: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OpsHeartbeat(Base):
    """Last-run stamps for background loops (worker, maintenance, reaper,
    alert evaluation) so the ops page can show a loop that silently died."""

    __tablename__ = "ops_heartbeats"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    last_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB)


class PricingSimulation(Base):
    __tablename__ = "pricing_simulations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    filters: Mapped[dict | None] = mapped_column(JSONB)
    baseline_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commercial_pricing_versions.id", ondelete="RESTRICT")
    )
    candidate_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commercial_pricing_versions.id", ondelete="RESTRICT")
    )
    provider_cost_basis: Mapped[str | None] = mapped_column(Text)
    transforms: Mapped[dict | None] = mapped_column(JSONB)
    config_hash: Mapped[str | None] = mapped_column(Text)
    manifest: Mapped[dict | None] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
