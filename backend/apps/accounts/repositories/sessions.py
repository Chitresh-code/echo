from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from apps.accounts.models.account import User
from apps.accounts.repositories.users import users
from core.db import metadata

sessions = sa.Table(
    "sessions", metadata,
    sa.Column("token_hash", sa.String, primary_key=True),
    sa.Column("user_id", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
)


async def add(db: AsyncSession, token_hash: str, user_id: str, created_at: datetime, expires_at: datetime) -> None:
    await db.execute(sessions.insert().values(token_hash=token_hash, user_id=user_id, created_at=created_at, expires_at=expires_at))


async def user_for(db: AsyncSession, token_hash: str, now: datetime) -> User | None:
    query = (
        sa.select(users.c.id, users.c.name, users.c.email)
        .join(sessions, sessions.c.user_id == users.c.id)
        .where(sessions.c.token_hash == token_hash, sessions.c.expires_at > now)
    )
    row = (await db.execute(query)).first()
    return User(id=row.id, name=row.name, email=row.email) if row else None


async def delete(db: AsyncSession, token_hash: str) -> None:
    await db.execute(sessions.delete().where(sessions.c.token_hash == token_hash))
