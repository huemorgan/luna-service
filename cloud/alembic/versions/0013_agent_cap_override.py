"""057 — per-account active-Luna cap override.

One nullable column on billing_accounts. NULL = pricing-config default.
Purely additive; metering untouched.

Revision ID: 0013
Revises: 0012
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0013'
down_revision: Union[str, None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'billing_accounts',
        sa.Column('active_luna_cap_override', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('billing_accounts', 'active_luna_cap_override')
