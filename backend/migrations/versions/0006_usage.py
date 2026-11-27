"""Usage ledger: tokens and estimated cost per turn and model, kept per user. Workspace, chat, turn
and key ids are plain strings, not foreign keys, so deleting any of them keeps what it cost; deleting
the user deletes their rows. Starts empty: older turns counted only their main model's tokens and
not which key they used, so they are left out rather than shown as if precise."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.create_table(
        "usage",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(32), nullable=False),
        sa.Column("chat_id", sa.String(32), nullable=False),
        sa.Column("turn_id", sa.String(32), nullable=False),
        sa.Column("credential_id", sa.String(64)),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("cache_read_tokens", sa.Integer, nullable=False),
        sa.Column("cache_write_tokens", sa.Integer, nullable=False),
        sa.Column("calls", sa.Integer, nullable=False),
        sa.Column("cost_micros", sa.BigInteger),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("usage_user_at", "usage", ["user_id", "at"])


def downgrade() -> None:
    op.drop_table("usage")
