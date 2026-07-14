"""039/010 — per-account enforcement override.

Nullable escalation over the global CLOUD_BILLING_MODE: the effective mode
for an account is max(global, override) on off < observe < shadow < enforce,
so internal canaries can be enforced without touching customers. NULL means
no override; the set-at timestamp records when the current value took effect
(who/why lives in audit_log).

Revision ID: 0007
Revises: 0006
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('billing_accounts', sa.Column('enforcement_override', sa.Text(), nullable=True))
    op.add_column('billing_accounts',
                  sa.Column('enforcement_override_set_at', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        'ck_billing_account_override', 'billing_accounts',
        "enforcement_override IN ('observe','shadow','enforce')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_billing_account_override', 'billing_accounts', type_='check')
    op.drop_column('billing_accounts', 'enforcement_override_set_at')
    op.drop_column('billing_accounts', 'enforcement_override')
