"""Coupon codes (plan 102).

Additive: coupons table — admin-issued single-use credit coupons, redeemed
from the customer billing page into a gift grant lot.

Revision ID: 0017
Revises: 0016
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0017'
down_revision: Union[str, None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'coupons',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('code', sa.Text(), nullable=False, unique=True),
        sa.Column('credits', sa.BigInteger(), nullable=False),
        sa.Column('expires_days', sa.Integer(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('redeemed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('redeemed_by_account_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('accounts.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('redeemed_by_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('grant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('credit_grants.id', ondelete='RESTRICT'), nullable=True),
        sa.CheckConstraint('credits > 0', name='ck_coupon_credits_positive'),
    )


def downgrade() -> None:
    op.drop_table('coupons')
