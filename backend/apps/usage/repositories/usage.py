"""The usage ledger. Every read takes the user id, so a user only ever sees their own rows."""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import metadata

usage = sa.Table(
    "usage", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("user_id", sa.String),
    sa.Column("agent_id", sa.String),
    sa.Column("chat_id", sa.String),
    sa.Column("turn_id", sa.String),
    sa.Column("credential_id", sa.String),
    sa.Column("provider", sa.String),
    sa.Column("model", sa.String),
    sa.Column("input_tokens", sa.Integer),
    sa.Column("output_tokens", sa.Integer),
    sa.Column("cache_read_tokens", sa.Integer),
    sa.Column("cache_write_tokens", sa.Integer),
    sa.Column("calls", sa.Integer),
    sa.Column("cost_micros", sa.BigInteger),
    sa.Column("at", sa.DateTime(timezone=True)),
)


async def add_rows(db: AsyncSession, rows: list[dict]) -> None:
    await db.execute(usage.insert(), rows)


async def rows_for(db: AsyncSession, user_id: str, start: datetime, end: datetime) -> list[dict]:
    """The user's rows with `start <= at < end`."""
    query = sa.select(usage).where(usage.c.user_id == user_id, usage.c.at >= start, usage.c.at < end)
    return [dict(r) for r in (await db.execute(query)).mappings()]


async def first_at(db: AsyncSession, user_id: str) -> datetime | None:
    """When the user's usage was first counted."""
    return (await db.execute(sa.select(sa.func.min(usage.c.at)).where(usage.c.user_id == user_id))).scalar()
