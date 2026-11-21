"""Each user's agents. Every read and write takes the owner, so an agent lookup that ignores the
owner cannot be written by mistake."""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from apps.agents.models.agent import Agent
from core.db import metadata

agents = sa.Table(
    "agents", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("owner_id", sa.String),
    sa.Column("name", sa.String),
    sa.Column("job", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("last_used_at", sa.DateTime(timezone=True)),
)
_FIELDS = (agents.c.id, agents.c.name, agents.c.job, agents.c.created_at, agents.c.last_used_at)


async def add(db: AsyncSession, agent_id: str, owner_id: str, name: str = "Untitled agent", job: str = "") -> Agent:
    row = {"id": agent_id, "name": name, "job": job, "created_at": datetime.now(UTC), "last_used_at": None}
    await db.execute(agents.insert().values(owner_id=owner_id, **row))
    return Agent(**row)


async def list_for(db: AsyncSession, owner_id: str) -> list[Agent]:
    # Most recently used first; an agent never used sorts by when it was made.
    recent = sa.func.coalesce(agents.c.last_used_at, agents.c.created_at)
    query = sa.select(*_FIELDS).where(agents.c.owner_id == owner_id).order_by(recent.desc())
    return [Agent(**row._mapping) for row in await db.execute(query)]


async def get(db: AsyncSession, agent_id: str, owner_id: str) -> Agent | None:
    query = sa.select(*_FIELDS).where(agents.c.id == agent_id, agents.c.owner_id == owner_id)
    row = (await db.execute(query)).first()
    return Agent(**row._mapping) if row else None


async def update(db: AsyncSession, agent_id: str, owner_id: str, fields: dict) -> None:
    await db.execute(agents.update().where(agents.c.id == agent_id, agents.c.owner_id == owner_id).values(**fields))


async def count_for(db: AsyncSession, owner_id: str) -> int:
    query = sa.select(sa.func.count()).select_from(agents).where(agents.c.owner_id == owner_id)
    return (await db.execute(query)).scalar_one()


async def delete(db: AsyncSession, agent_id: str, owner_id: str) -> None:
    await db.execute(agents.delete().where(agents.c.id == agent_id, agents.c.owner_id == owner_id))


async def touch(db: AsyncSession, agent_id: str) -> None:
    await db.execute(agents.update().where(agents.c.id == agent_id).values(last_used_at=datetime.now(UTC)))


async def owns(db: AsyncSession, agent_id: str, owner_id: str) -> bool:
    query = sa.select(agents.c.id).where(agents.c.id == agent_id, agents.c.owner_id == owner_id)
    return (await db.execute(query)).first() is not None
