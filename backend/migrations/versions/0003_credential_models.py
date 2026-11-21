"""OpenAI-compatible keys can carry the model ids the user typed, for endpoints with no model list."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    with op.batch_alter_table("credentials") as batch:
        batch.add_column(sa.Column("models", sa.JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("credentials") as batch:
        batch.drop_column("models")
