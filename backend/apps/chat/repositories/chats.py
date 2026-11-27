"""Stored chats, their turns and each turn's events. Every read takes the agent id, and routes only
pass an agent the user owns, so a chat is reachable only through its own agent."""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import metadata

chats = sa.Table(
    "chats", metadata,
    sa.Column("agent_id", sa.String, primary_key=True),
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("title", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)
turns = sa.Table(
    "turns", metadata,
    sa.Column("n", sa.Integer, primary_key=True),
    sa.Column("id", sa.String),
    sa.Column("agent_id", sa.String),
    sa.Column("chat_id", sa.String),
    sa.Column("prompt", sa.Text),
    sa.Column("model", sa.String),
    sa.Column("effort", sa.String),
    sa.Column("status", sa.String),
    sa.Column("usage", sa.JSON),
    sa.Column("truncated", sa.Boolean),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("ended_at", sa.DateTime(timezone=True)),
)
turn_events = sa.Table(
    "turn_events", metadata,
    sa.Column("turn_id", sa.String, primary_key=True),
    sa.Column("seq", sa.Integer, primary_key=True),
    sa.Column("event", sa.String),
    sa.Column("data", sa.JSON),
)
_CHAT = (chats.c.id, chats.c.title, chats.c.created_at, chats.c.updated_at)
_TURN = (turns.c.n, turns.c.id, turns.c.prompt, turns.c.model, turns.c.effort, turns.c.status, turns.c.usage, turns.c.truncated, turns.c.started_at, turns.c.ended_at)


async def seen(db: AsyncSession, agent_id: str, chat_id: str, title: str, at: datetime) -> None:
    """Adds the chat on its first turn and marks it used on every later one; the title is the
    first turn's only."""
    query = insert(chats).values(agent_id=agent_id, id=chat_id, title=title, created_at=at, updated_at=at)
    await db.execute(query.on_conflict_do_update(index_elements=["agent_id", "id"], set_={"updated_at": at}))


async def add_turn(db: AsyncSession, row: dict) -> None:
    await db.execute(turns.insert().values(status="running", truncated=False, **row))


async def add_events(db: AsyncSession, turn_id: str, rows: list[tuple[int, str, dict]]) -> None:
    if rows:
        # Replaces rather than adds: the last text row of a running turn is written again once more of it has arrived.
        query = insert(turn_events).values([{"turn_id": turn_id, "seq": s, "event": e, "data": d} for s, e, d in rows])
        await db.execute(query.on_conflict_do_update(index_elements=["turn_id", "seq"], set_={"event": query.excluded.event, "data": query.excluded.data}))


async def end_turn(db: AsyncSession, turn_id: str, status: str, usage: dict | None, truncated: bool, at: datetime) -> None:
    await db.execute(turns.update().where(turns.c.id == turn_id).values(status=status, usage=usage, truncated=truncated, ended_at=at))


async def interrupt_running(db: AsyncSession) -> int:
    """Turns left running by a stopped api; nothing is running them any more."""
    query = turns.update().where(turns.c.status == "running").values(status="interrupted", ended_at=datetime.now(UTC))
    return (await db.execute(query)).rowcount


async def list_for(db: AsyncSession, agent_id: str, limit: int, before: tuple[datetime, str] | None = None) -> list[dict]:
    """Most recently used first, `limit` at a time, after the (updated_at, id) of the last one shown."""
    query = sa.select(*_CHAT).where(chats.c.agent_id == agent_id)
    if before:
        at, chat_id = before
        query = query.where(sa.or_(chats.c.updated_at < at, sa.and_(chats.c.updated_at == at, chats.c.id < chat_id)))
    query = query.order_by(chats.c.updated_at.desc(), chats.c.id.desc()).limit(limit)
    return [dict(row._mapping) for row in await db.execute(query)]


async def get(db: AsyncSession, agent_id: str, chat_id: str) -> dict | None:
    row = (await db.execute(sa.select(*_CHAT).where(chats.c.agent_id == agent_id, chats.c.id == chat_id))).first()
    return dict(row._mapping) if row else None


async def turns_page(db: AsyncSession, agent_id: str, chat_id: str, limit: int, before: int | None = None) -> list[dict]:
    """The newest `limit` turns before turn number `before`, oldest first, each with its events."""
    query = sa.select(*_TURN).where(turns.c.agent_id == agent_id, turns.c.chat_id == chat_id)
    if before is not None:
        query = query.where(turns.c.n < before)
    rows = [dict(r._mapping) for r in await db.execute(query.order_by(turns.c.n.desc()).limit(limit))][::-1]
    events = await _events(db, [r["id"] for r in rows])
    for row in rows:
        row["events"] = events.get(row["id"], [])
    return rows


async def turn(db: AsyncSession, agent_id: str, chat_id: str, turn_id: str) -> dict | None:
    query = sa.select(*_TURN).where(turns.c.agent_id == agent_id, turns.c.chat_id == chat_id, turns.c.id == turn_id)
    row = (await db.execute(query)).first()
    if not row:
        return None
    found = dict(row._mapping)
    found["events"] = (await _events(db, [turn_id])).get(turn_id, [])
    return found


async def _events(db: AsyncSession, turn_ids: list[str]) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {}
    if turn_ids:
        query = sa.select(turn_events).where(turn_events.c.turn_id.in_(turn_ids)).order_by(turn_events.c.turn_id, turn_events.c.seq)
        for row in await db.execute(query):
            found.setdefault(row.turn_id, []).append({"event": row.event, "data": row.data})
    return found


async def delete(db: AsyncSession, agent_id: str, chat_id: str) -> None:
    await db.execute(chats.delete().where(chats.c.agent_id == agent_id, chats.c.id == chat_id))


async def ids_for(db: AsyncSession, agent_id: str) -> set[str]:
    return set((await db.execute(sa.select(chats.c.id).where(chats.c.agent_id == agent_id))).scalars())
