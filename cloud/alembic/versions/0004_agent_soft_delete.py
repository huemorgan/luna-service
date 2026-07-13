"""039/005 — agents.deleted_at soft-delete tombstone.

Billing tables reference agents with ON DELETE RESTRICT (financial and usage
attribution is permanent), so agents become tombstones instead of being
hard-deleted once any billing row exists.

Revision ID: 0004
Revises: 0003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "deleted_at")
