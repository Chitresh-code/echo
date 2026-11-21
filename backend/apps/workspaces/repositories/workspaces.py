"""Who owns each workspace. Every read takes the owner, so a workspace lookup that ignores the
owner cannot be written by mistake."""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import metadata

workspaces = sa.Table(
    "workspaces", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("owner_id", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


async def add(db: AsyncSession, workspace_id: str, owner_id: str) -> None:
    await db.execute(workspaces.insert().values(id=workspace_id, owner_id=owner_id, created_at=datetime.now(UTC)))


async def list_for(db: AsyncSession, owner_id: str) -> list[str]:
    query = sa.select(workspaces.c.id).where(workspaces.c.owner_id == owner_id).order_by(workspaces.c.created_at.desc())
    return list((await db.execute(query)).scalars())


async def owns(db: AsyncSession, workspace_id: str, owner_id: str) -> bool:
    query = sa.select(workspaces.c.id).where(workspaces.c.id == workspace_id, workspaces.c.owner_id == owner_id)
    return (await db.execute(query)).first() is not None
