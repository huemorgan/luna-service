"""040 — cost benchmark tables.

Live-fire cost benchmark runs against designated test agents: per-run and
per-step aggregates plus the full trigger log (one row per billable event
observed in a step window). No prompts, outputs, or tool arguments are ever
stored — steps reference versioned playbook item keys in code.

Revision ID: 0008
Revises: 0007
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'benchmark_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('created_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('agent_id', UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('account_id', UUID(as_uuid=True),
                  sa.ForeignKey('billing_accounts.account_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('image_version', sa.Text(), nullable=True),
        sa.Column('playbook_version', sa.Text(), nullable=False),
        sa.Column('item_keys', JSONB(), nullable=False),
        sa.Column('repetitions', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('state', sa.Text(), nullable=False, server_default='pending'),
        sa.Column('progress', JSONB(), nullable=True),
        sa.Column('totals', JSONB(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending','running','succeeded','failed','aborted')",
            name='ck_bench_run_state',
        ),
    )
    op.create_table(
        'benchmark_steps',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True),
                  sa.ForeignKey('benchmark_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('item_key', sa.Text(), nullable=False),
        sa.Column('repetition', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.Text(), nullable=False, server_default='running'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('llm_requests', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('input_tokens', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('cache_read_tokens', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('cache_write_tokens', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('per_model', JSONB(), nullable=True),
        sa.Column('credits', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('vendor_cost_micro_usd', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('margin_micro_usd', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed','skipped')",
            name='ck_bench_step_status',
        ),
    )
    op.create_index('ix_bstep_run', 'benchmark_steps', ['run_id', 'seq'])
    op.create_table(
        'benchmark_step_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True),
                  sa.ForeignKey('benchmark_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('step_id', UUID(as_uuid=True),
                  sa.ForeignKey('benchmark_steps.id', ondelete='CASCADE'), nullable=False),
        sa.Column('billable_event_id', UUID(as_uuid=True),
                  sa.ForeignKey('billable_events.id', ondelete='SET NULL'), nullable=True),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('call_id', sa.Text(), nullable=True),
        sa.Column('service', sa.Text(), nullable=False),
        sa.Column('sku', sa.Text(), nullable=True),
        sa.Column('provider', sa.Text(), nullable=True),
        sa.Column('model', sa.Text(), nullable=True),
        sa.Column('attempt_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('quantities', JSONB(), nullable=True),
        sa.Column('vendor_cost_micro_usd', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('credits', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('cost_source', sa.Text(), nullable=True),
    )
    op.create_index('ix_bsev_run', 'benchmark_step_events', ['run_id'])
    op.create_index('ix_bsev_step', 'benchmark_step_events', ['step_id'])


def downgrade() -> None:
    op.drop_index('ix_bsev_step', table_name='benchmark_step_events')
    op.drop_index('ix_bsev_run', table_name='benchmark_step_events')
    op.drop_table('benchmark_step_events')
    op.drop_index('ix_bstep_run', table_name='benchmark_steps')
    op.drop_table('benchmark_steps')
    op.drop_table('benchmark_runs')
