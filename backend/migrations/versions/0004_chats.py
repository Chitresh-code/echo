"""Chats are stored: each chat of an agent, its turns, and the events each turn showed in the chat.
The harness's session folders stay where they are; they remain what the model reads."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    # Keyed by agent and chat, so a chat id reused under another agent never reaches this chat.
    op.create_table(
        "chats",
        sa.Column("agent_id", sa.String(32), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chats_agent_updated", "chats", ["agent_id", "updated_at"])
    op.create_table(
        "turns",
        # Increasing, so it orders a chat's turns and pages through them.
        sa.Column("n", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("id", sa.String(32), nullable=False, unique=True),
        sa.Column("agent_id", sa.String(32), nullable=False),
        sa.Column("chat_id", sa.String(32), nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("effort", sa.String(16), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("usage", sa.JSON, nullable=True),
        sa.Column("truncated", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id", "chat_id"], ["chats.agent_id", "chats.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_turns_chat", "turns", ["agent_id", "chat_id", "n"])
    op.create_table(
        "turn_events",
        sa.Column("turn_id", sa.String(32), sa.ForeignKey("turns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("seq", sa.Integer, primary_key=True),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("data", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("turn_events")
    op.drop_index("ix_turns_chat", "turns")
    op.drop_table("turns")
    op.drop_index("ix_chats_agent_updated", "chats")
    op.drop_table("chats")
