"""Stored MCP servers and which agents use them. Every read takes the owner, so a lookup that
ignores the owner cannot be written by mistake, and an agent's servers are joined through the owner
too, so an assignment row can never pull in another user's server."""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import metadata

mcp_servers = sa.Table(
    "mcp_servers", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("owner_id", sa.String),
    sa.Column("name", sa.String),
    sa.Column("kind", sa.String),
    sa.Column("url", sa.String),
    sa.Column("auth", sa.String),
    sa.Column("command", sa.String),
    sa.Column("args", sa.JSON),
    sa.Column("secret", sa.LargeBinary),
    sa.Column("status", sa.String),
    sa.Column("tools", sa.JSON),
    sa.Column("tools_hash", sa.String),
    sa.Column("pending_tools", sa.JSON),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)
agent_mcp_servers = sa.Table(
    "agent_mcp_servers", metadata,
    sa.Column("agent_id", sa.String, primary_key=True),
    sa.Column("server_id", sa.String, primary_key=True),
)


async def add(db: AsyncSession, owner_id: str, **fields) -> dict:
    row = {"id": uuid.uuid4().hex, "owner_id": owner_id, "created_at": datetime.now(UTC), "pending_tools": None, **fields}
    await db.execute(mcp_servers.insert().values(**row))
    return row


async def count_for(db: AsyncSession, owner_id: str) -> int:
    return (await db.execute(sa.select(sa.func.count()).select_from(mcp_servers).where(mcp_servers.c.owner_id == owner_id))).scalar_one()


async def name_taken(db: AsyncSession, owner_id: str, name: str) -> bool:
    query = sa.select(mcp_servers.c.id).where(mcp_servers.c.owner_id == owner_id, mcp_servers.c.name == name)
    return (await db.execute(query)).first() is not None


async def list_for(db: AsyncSession, owner_id: str) -> list[dict]:
    query = sa.select(mcp_servers).where(mcp_servers.c.owner_id == owner_id).order_by(mcp_servers.c.name)
    return [dict(row._mapping) for row in await db.execute(query)]


async def get(db: AsyncSession, server_id: str, owner_id: str) -> dict | None:
    """The whole row with its encrypted secret, or None when it is missing or someone else's."""
    query = sa.select(mcp_servers).where(mcp_servers.c.id == server_id, mcp_servers.c.owner_id == owner_id)
    row = (await db.execute(query)).first()
    return dict(row._mapping) if row else None


async def update(db: AsyncSession, server_id: str, owner_id: str, **fields) -> None:
    """Sets `fields` (secret, status, tools, tools_hash, pending_tools) on the owner's server."""
    await db.execute(mcp_servers.update().where(mcp_servers.c.id == server_id, mcp_servers.c.owner_id == owner_id).values(**fields))


async def delete(db: AsyncSession, server_id: str, owner_id: str) -> bool:
    result = await db.execute(mcp_servers.delete().where(mcp_servers.c.id == server_id, mcp_servers.c.owner_id == owner_id))
    return result.rowcount > 0


async def for_agent(db: AsyncSession, agent_id: str, owner_id: str) -> list[dict]:
    query = (
        sa.select(mcp_servers)
        .join(agent_mcp_servers, agent_mcp_servers.c.server_id == mcp_servers.c.id)
        .where(agent_mcp_servers.c.agent_id == agent_id, mcp_servers.c.owner_id == owner_id)
        .order_by(mcp_servers.c.name)
    )
    return [dict(row._mapping) for row in await db.execute(query)]


async def set_for_agent(db: AsyncSession, agent_id: str, server_ids: list[str]) -> None:
    """Replaces the agent's servers. The caller has checked the agent and every server are the user's."""
    await db.execute(agent_mcp_servers.delete().where(agent_mcp_servers.c.agent_id == agent_id))
    if server_ids:
        await db.execute(agent_mcp_servers.insert(), [{"agent_id": agent_id, "server_id": s} for s in server_ids])
