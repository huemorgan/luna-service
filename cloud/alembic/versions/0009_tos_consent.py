"""044 — Terms of Service consent tracking.

Records which TOS version a user accepted and when. Set on every login
through the consent-bearing flow whenever the stored version differs from
the current one; NULL means the user predates the TOS and has not signed
in since it shipped.

Revision ID: 0009
Revises: 0008
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('tos_version', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('tos_accepted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'tos_accepted_at')
    op.drop_column('users', 'tos_version')
