"""046 — feedback tickets (agent + owner → admin, threaded).

Two new tables, purely additive. `feedback_tickets` holds thread summary +
state; `feedback_messages` holds each message (the opening message is a row
too). All ticket state lives on the control plane. No changes to existing
tables, no data touched.

Revision ID: 0011
Revises: 0010
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0011'
down_revision: Union[str, None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'feedback_tickets',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('origin', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('severity', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_admin_reply_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_client_reply_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('agent_read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_feedback_tickets_status_updated', 'feedback_tickets', ['status', 'updated_at'])
    op.create_index('ix_feedback_tickets_agent_updated', 'feedback_tickets', ['agent_id', 'updated_at'])
    op.create_index('ix_feedback_tickets_created', 'feedback_tickets', ['created_at'])

    op.create_table(
        'feedback_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('ticket_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('author', sa.Text(), nullable=False),
        sa.Column('admin_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['feedback_tickets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['admin_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_feedback_messages_ticket_created', 'feedback_messages', ['ticket_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_feedback_messages_ticket_created', table_name='feedback_messages')
    op.drop_table('feedback_messages')
    op.drop_index('ix_feedback_tickets_created', table_name='feedback_tickets')
    op.drop_index('ix_feedback_tickets_agent_updated', table_name='feedback_tickets')
    op.drop_index('ix_feedback_tickets_status_updated', table_name='feedback_tickets')
    op.drop_table('feedback_tickets')
