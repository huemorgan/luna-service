"""feedback_tickets.client_ref — idempotent ticket creates (plan 078/7b).

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedback_tickets", sa.Column("client_ref", sa.Text(), nullable=True))
    # Unique on non-NULL only (Postgres semantics) — history is unaffected.
    op.create_index(
        "ux_feedback_tickets_client_ref",
        "feedback_tickets",
        ["client_ref"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_feedback_tickets_client_ref", table_name="feedback_tickets")
    op.drop_column("feedback_tickets", "client_ref")
