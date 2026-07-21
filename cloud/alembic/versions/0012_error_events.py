"""051 — error_events (unified error tracking).

One new table, purely additive. Raw error events from three sources (agent,
ui via plugin-feedback; service via the in-process sink). Grouping is a query
over `fingerprint`; no pre-aggregation. No changes to existing tables.

Revision ID: 0012
Revises: 0011
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0012'
down_revision: Union[str, None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'error_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('severity', sa.Text(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('fingerprint', sa.Text(), nullable=False),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_error_events_fingerprint', 'error_events', ['fingerprint'])
    op.create_index('ix_error_events_source_created', 'error_events', ['source', 'created_at'])
    op.create_index('ix_error_events_agent_created', 'error_events', ['agent_id', 'created_at'])
    op.create_index('ix_error_events_severity_created', 'error_events', ['severity', 'created_at'])
    op.create_index('ix_error_events_kind_created', 'error_events', ['kind', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_error_events_kind_created', table_name='error_events')
    op.drop_index('ix_error_events_severity_created', table_name='error_events')
    op.drop_index('ix_error_events_agent_created', table_name='error_events')
    op.drop_index('ix_error_events_source_created', table_name='error_events')
    op.drop_index('ix_error_events_fingerprint', table_name='error_events')
    op.drop_table('error_events')
