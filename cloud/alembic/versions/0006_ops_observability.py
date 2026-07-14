"""039/009 — operations observability tables.

- ops_alerts: one row per alert key; active alerts refresh in place and a
  re-fire inside the dedupe window reactivates the same row (no incident
  storms from a flapping signal).
- ops_heartbeats: last-run stamps for the background loops (outbox worker,
  billing maintenance, stale-hold reaper, alert evaluation) so a silently
  dead loop is visible on the ops page.

Revision ID: 0006
Revises: 0005
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('ops_alerts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('alert_key', sa.Text(), nullable=False),
    sa.Column('severity', sa.Text(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('value_json', JSONB(), nullable=True),
    sa.Column('threshold_json', JSONB(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("severity IN ('info','warning','critical')", name='ck_oa_severity'),
    sa.CheckConstraint("status IN ('active','resolved')", name='ck_oa_status'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('alert_key')
    )
    op.create_table('ops_heartbeats',
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('detail', JSONB(), nullable=True),
    sa.PrimaryKeyConstraint('name')
    )


def downgrade() -> None:
    op.drop_table('ops_heartbeats')
    op.drop_table('ops_alerts')
