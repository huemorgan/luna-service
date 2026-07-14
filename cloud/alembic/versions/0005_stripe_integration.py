"""039/007 — Stripe integration tables.

- stripe_price_bindings: catalog product key → Stripe Price per mode;
  bindings gate checkout activation (catalog publication stays decoupled).
- stripe_subscriptions: the account's single Luna Credits subscription,
  mirrored only from canonical Stripe objects.
- stripe_payments: payment-level clawback accumulator shared by refunds
  and disputes so proportional reversal never double-claws.

Revision ID: 0005
Revises: 0004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('stripe_price_bindings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('livemode', sa.Boolean(), nullable=False),
    sa.Column('product_key', sa.Text(), nullable=False),
    sa.Column('stripe_product_id', sa.Text(), nullable=False),
    sa.Column('stripe_price_id', sa.Text(), nullable=False),
    sa.Column('price_usd_cents', sa.BigInteger(), nullable=False),
    sa.Column('interval', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('livemode', 'product_key')
    )
    op.create_table('stripe_subscriptions',
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('stripe_subscription_id', sa.Text(), nullable=False),
    sa.Column('product_key', sa.Text(), nullable=False),
    sa.Column('stripe_price_id', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False),
    sa.Column('pending_product_key', sa.Text(), nullable=True),
    sa.Column('payment_action_required', sa.Boolean(), nullable=False),
    sa.Column('next_payment_retry_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['billing_accounts.account_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('account_id'),
    sa.UniqueConstraint('stripe_subscription_id')
    )
    op.create_table('stripe_payments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('payment_ref', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('product_key', sa.Text(), nullable=False),
    sa.Column('commercial_pricing_version_id', sa.UUID(), nullable=True),
    sa.Column('currency', sa.Text(), nullable=False),
    sa.Column('pretax_amount_cents', sa.BigInteger(), nullable=False),
    sa.Column('tax_amount_cents', sa.BigInteger(), nullable=False),
    sa.Column('granted_credits', sa.BigInteger(), nullable=False),
    sa.Column('refunded_pretax_cents', sa.BigInteger(), nullable=False),
    sa.Column('clawed_credits', sa.BigInteger(), nullable=False),
    sa.Column('dispute_status', sa.Text(), nullable=True),
    sa.Column('stripe_charge_id', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('subscription','topup')", name='ck_sp_kind'),
    sa.CheckConstraint("dispute_status IS NULL OR dispute_status IN ('created','won','lost')", name='ck_sp_dispute'),
    sa.CheckConstraint('refunded_pretax_cents >= 0 AND refunded_pretax_cents <= pretax_amount_cents', name='ck_sp_refund_bounds'),
    sa.ForeignKeyConstraint(['account_id'], ['billing_accounts.account_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['commercial_pricing_version_id'], ['commercial_pricing_versions.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('payment_ref')
    )
    op.create_index('ix_stripe_payments_account', 'stripe_payments', ['account_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_stripe_payments_account', table_name='stripe_payments')
    op.drop_table('stripe_payments')
    op.drop_table('stripe_subscriptions')
    op.drop_table('stripe_price_bindings')
