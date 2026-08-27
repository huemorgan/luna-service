"""Generic webhook gateway (plan 076).

Additive: new webhook_endpoints table (minted per-agent inbound webhook
URLs) and a nullable target_path on relay_deliveries so the forwarder can
carry deliveries to arbitrary plugin routes (NULL = legacy composio path).

Revision ID: 0016
Revises: 0015
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0016'
down_revision: Union[str, None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'webhook_endpoints',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('hook_slug', sa.Text(), nullable=False, unique=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('plugin', sa.Text(), nullable=False),
        sa.Column('target_path', sa.Text(), nullable=False),
        sa.Column('mode', sa.Text(), nullable=False, server_default='sync'),
        sa.Column('secret', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_delivery_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivery_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_status_code', sa.Integer(), nullable=True),
        sa.UniqueConstraint('agent_id', 'plugin', 'name'),
    )
    op.create_index('ix_webhook_endpoints_agent', 'webhook_endpoints', ['agent_id'])
    op.add_column('relay_deliveries', sa.Column('target_path', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('relay_deliveries', 'target_path')
    op.drop_index('ix_webhook_endpoints_agent', table_name='webhook_endpoints')
    op.drop_table('webhook_endpoints')
