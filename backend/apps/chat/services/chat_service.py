"""Stored chats as the API shows them: the database's record, with any turn still running (or not
yet written) taken from memory, since a running turn's freshest events are only there."""

import asyncio
import shutil

from sqlalchemy.ext.asyncio import AsyncSession

from apps.agents.services.paths import AGENT_ID, check_agent_id
from apps.chat.models.chat import ChatDetail, ChatList, ChatSummary, StoredTurn
from apps.chat.repositories import chats
from apps.chat.services import turn_service
from core.config import Settings
from core.errors import AppError

CHATS_PAGE = 50
TURNS_PAGE = 30


def check_id(value: str, what: str = "chat") -> str:
    # Chat ids name harness session folders, so they get the same check as agent ids.
    if not AGENT_ID.fullmatch(value):
        raise AppError(400, f"invalid_{what}_id", f"A {what} id is 32 lowercase hex characters.")
    return value


def _not_found() -> AppError:
    return AppError(404, "chat_not_found", "This chat does not exist. It may have been deleted.")


def _running_chats(agent_id: str) -> dict[str, turn_service.LiveTurn]:
    return {t.chat_id: t for t in turn_service.live_in(agent_id) if t.running}


async def list_chats(db: AsyncSession, agent_id: str, before: str | None) -> ChatList:
    cursor = None
    if before:
        if not (anchor := await chats.get(db, agent_id, check_id(before))):
            raise _not_found()
        cursor = (anchor["updated_at"], anchor["id"])
    rows = await chats.list_for(db, agent_id, CHATS_PAGE + 1, cursor)
    more, rows = len(rows) > CHATS_PAGE, rows[:CHATS_PAGE]
    running = _running_chats(agent_id)
    listed = {r["id"] for r in rows}
    if before is None:
        # A chat whose first turn has started but whose row is not written yet is still listed.
        for turn in turn_service.live_in(agent_id):
            if turn.chat_id not in listed:
                rows.insert(0, {"id": turn.chat_id, "title": turn.title, "created_at": turn.started_at, "updated_at": turn.started_at})
                listed.add(turn.chat_id)
    return ChatList(chats=[ChatSummary(**r, running=r["id"] in running) for r in rows], more=more)


async def chat_detail(db: AsyncSession, agent_id: str, chat_id: str, before: str | None) -> ChatDetail:
    check_id(chat_id)
    row = await chats.get(db, agent_id, chat_id)
    live = turn_service.live_in(agent_id, chat_id)
    if row is None:
        if not live:
            raise _not_found()
        row = {"id": chat_id, "title": live[0].title, "created_at": live[0].started_at, "updated_at": live[-1].started_at}
    before_n = None
    if before:
        if not (anchor := await chats.turn(db, agent_id, chat_id, check_id(before, "turn"))):
            raise AppError(404, "turn_not_found", "This turn is not part of the chat.")
        before_n = anchor["n"]
    turns = await chats.turns_page(db, agent_id, chat_id, TURNS_PAGE + 1, before_n)
    more, turns = len(turns) > TURNS_PAGE, turns[-TURNS_PAGE:] if len(turns) > TURNS_PAGE else turns
    if before is None:
        # Live turns are the newest, and memory holds more of them than the database yet does.
        by_id = {t.id: t for t in live}
        turns = [by_id.pop(t["id"]).stored() if t["id"] in by_id else t for t in turns]
        turns += [t.stored() for t in by_id.values()]
    return ChatDetail(**row, running=any(t.running for t in live), turns=[StoredTurn(**t) for t in turns], more=more)


async def stored_turn(db: AsyncSession, agent_id: str, chat_id: str, turn_id: str) -> dict:
    found = await chats.turn(db, agent_id, check_id(chat_id), check_id(turn_id, "turn"))
    if not found:
        raise AppError(404, "turn_not_found", "This turn is not part of the chat.")
    return found


def live_turn(agent_id: str, chat_id: str, turn_id: str) -> turn_service.LiveTurn | None:
    turn = turn_service.live(check_id(turn_id, "turn"))
    return turn if turn and turn.agent_id == agent_id and turn.chat_id == check_id(chat_id) else None


async def delete_chat(settings: Settings, db: AsyncSession, agent_id: str, chat_id: str) -> None:
    """The harness's folders first and the row last, so a failure part way leaves the chat listed
    and the delete can be repeated; every step skips what is already gone."""
    check_id(chat_id)
    if turn_service.live_in(agent_id, chat_id):
        raise AppError(409, "chat_busy", "This chat has a turn in progress. Stop it or wait for it to end, then delete.")
    if await chats.get(db, agent_id, chat_id) is None:
        raise _not_found()
    base = settings.data_dir / "sessions" / check_agent_id(agent_id)
    for folder in ("session", "context"):
        await asyncio.to_thread(shutil.rmtree, base / folder / chat_id, ignore_errors=True)
    await chats.delete(db, agent_id, chat_id)
    await db.commit()
