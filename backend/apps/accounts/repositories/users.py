import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from apps.accounts.models.account import User
from core.db import metadata

users = sa.Table(
    "users", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("tenant_id", sa.String),
    sa.Column("object_id", sa.String),
    sa.Column("email", sa.String),
    sa.Column("name", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("last_login_at", sa.DateTime(timezone=True)),
)


async def sign_in(db: AsyncSession, tenant_id: str, object_id: str, email: str | None, name: str | None) -> User:
    """Find the user by their Entra ids, or add them, and record this sign-in. Name and email follow
    whatever Entra says now; they are never used to find the user."""
    now = datetime.now(UTC)
    row = (await db.execute(sa.select(users.c.id).where(users.c.tenant_id == tenant_id, users.c.object_id == object_id))).first()
    if row:
        user_id = row.id
        await db.execute(users.update().where(users.c.id == user_id).values(email=email, name=name, last_login_at=now))
    else:
        user_id = uuid.uuid4().hex
        await db.execute(users.insert().values(id=user_id, tenant_id=tenant_id, object_id=object_id, email=email, name=name, created_at=now, last_login_at=now))
    return User(id=user_id, name=name, email=email)
