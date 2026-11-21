"""Users, sign-in sessions, workspace owners and stored provider keys."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        # A user is the Entra tenant and object id pair, never the email, which a user can change.
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("object_id", sa.String(36), nullable=False),
        sa.Column("email", sa.String, nullable=True),
        sa.Column("name", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "object_id"),
    )
    op.create_table(
        "sessions",
        # Only the SHA-256 of the cookie is kept, so a copy of the database cannot sign anyone in.
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "credentials",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("provider", sa.String, nullable=False),
        sa.Column("label", sa.String, nullable=False),
        sa.Column("base_url", sa.String, nullable=True),
        # The last four characters, so a user can tell keys apart without the key ever being shown.
        sa.Column("key_hint", sa.String(4), nullable=False),
        sa.Column("key_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in ("credentials", "workspaces", "sessions", "users"):
        op.drop_table(table)
