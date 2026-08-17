"""Feedback — admin read marker (unread badge in admin nav).

Additive: one nullable timestamp on feedback_tickets. A ticket is unread by
the team when the client last spoke after admin_read_at (or it was never
opened). Set when an admin opens or replies to the ticket.

Revision ID: 0015
Revises: 0014
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0015'
down_revision: Union[str, None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'feedback_tickets',
        sa.Column('admin_read_at', sa.DateTime(timezone=True), nullable=True),
    )
    # Existing tickets: treat anything the team already answered as read.
    op.execute(
        "UPDATE feedback_tickets SET admin_read_at = last_admin_reply_at "
        "WHERE last_admin_reply_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column('feedback_tickets', 'admin_read_at')
