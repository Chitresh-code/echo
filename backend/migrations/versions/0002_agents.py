"""Workspaces become agents: the table is renamed and gains a name, the job the agent does, and when
it was last used. The agent's files on the sandbox volume keep their place, so nothing moves."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.rename_table("workspaces", "agents")
    # Batch mode, so the downgrade's column drops work on SQLite too.
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("name", sa.String(80), nullable=False, server_default="Untitled agent"))
        batch.add_column(sa.Column("job", sa.String(500), nullable=False, server_default=""))
        batch.add_column(sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("last_used_at")
        batch.drop_column("job")
        batch.drop_column("name")
    op.rename_table("agents", "workspaces")
