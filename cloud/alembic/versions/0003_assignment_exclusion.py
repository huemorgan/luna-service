"""039/002 — DB-level backstop: commercial pricing assignment intervals for
one account can never overlap.

Postgres-only (btree_gist + gist exclusion constraint); SQLite test databases
rely on the identical service-layer check in cloud/billing/assignments.py.
A NULL ends_at is an unbounded-upper range, so two open intervals for the
same account are also rejected.

Revision ID: 0003
Revises: 0002
"""

from typing import Sequence, Union

from alembic import op

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        ALTER TABLE commercial_pricing_assignments
        ADD CONSTRAINT excl_cpa_no_overlap
        EXCLUDE USING gist (
            account_id WITH =,
            tstzrange(effective_at, ends_at) WITH &&
        )
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE commercial_pricing_assignments DROP CONSTRAINT IF EXISTS excl_cpa_no_overlap"
    )
