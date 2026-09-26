"""Chat feed for the Luna iPhone app: chat_index, chat_events, chat_read_markers,
agents.chat_previews (luna-control plan 002, phase 3).

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("chat_previews", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "chat_index",
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("conversation_id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text()),
        sa.Column("kind", sa.Text()),
        sa.Column("state", sa.Text()),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("last_role", sa.Text()),
        sa.Column("preview", sa.Text()),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_chat_index_agent_last", "chat_index", ["agent_id", "last_message_at"])

    op.create_table(
        "chat_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.Text()),
        sa.Column("approval_id", sa.Text()),
        sa.Column("role", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "event_id", name="uq_chat_events_agent_event"),
    )
    op.create_index("ix_chat_events_conv", "chat_events", ["agent_id", "conversation_id", "occurred_at"])
    op.create_index("ix_chat_events_approval", "chat_events", ["agent_id", "approval_id"])
    op.create_index("ix_chat_events_created", "chat_events", ["created_at"])

    op.create_table(
        "chat_read_markers",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("conversation_id", sa.Text(), primary_key=True),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("chat_read_markers")
    op.drop_table("chat_events")
    op.drop_table("chat_index")
    op.drop_column("agents", "chat_previews")
