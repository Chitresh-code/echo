"""Tool approvals and MCP servers. Each agent asks before tools that change something, unless its
owner switches it to yolo; existing agents start asking too. A user's MCP servers are stored with
their secrets encrypted, and each agent is given some of them."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.add_column("agents", sa.Column("approval_mode", sa.String(8), nullable=False, server_default="ask"))
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("url", sa.String(500)),
        sa.Column("auth", sa.String(8)),
        sa.Column("command", sa.Text),
        sa.Column("args", sa.JSON),
        sa.Column("secret", sa.LargeBinary),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("tools", sa.JSON, nullable=False),
        sa.Column("tools_hash", sa.String(64)),
        sa.Column("pending_tools", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "name"),
    )
    op.create_table(
        "agent_mcp_servers",
        sa.Column("agent_id", sa.String(32), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("server_id", sa.String(32), sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"), primary_key=True, index=True),
    )


def downgrade() -> None:
    op.drop_table("agent_mcp_servers")
    op.drop_table("mcp_servers")
    op.drop_column("agents", "approval_mode")
