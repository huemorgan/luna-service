"""046 — per-channel credit attribution.

Adds `billable_events.channel` (who initiated the work: web | whatsapp |
telegram | scheduler | api). Additive and nullable — existing rows keep
NULL (surfaced as legacy/web in the usage UI). No backfill, no drops.

Revision ID: 0010
Revises: 0009
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('billable_events', sa.Column('channel', sa.Text(), nullable=True))
    op.create_index(
        'ix_be_account_channel_event_at',
        'billable_events',
        ['account_id', 'channel', 'event_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_be_account_channel_event_at', table_name='billable_events')
    op.drop_column('billable_events', 'channel')
