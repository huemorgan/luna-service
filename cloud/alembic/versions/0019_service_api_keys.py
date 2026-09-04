"""Service API keys (plan 088).

Additive: service_api_keys table — generated, scoped, revocable keys for
luna-service admin APIs (first consumer: feedback triage by a Luna agent).

Revision ID: 0019
Revises: 0018
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0019'
down_revision: Union[str, None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'service_api_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('key_hash', sa.Text(), nullable=False, unique=True),
        sa.Column('key_prefix', sa.Text(), nullable=False),
        sa.Column('scopes', postgresql.JSONB(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_service_api_keys_created', 'service_api_keys', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_service_api_keys_created', table_name='service_api_keys')
    op.drop_table('service_api_keys')
