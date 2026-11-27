"""Chats from before chats were stored: rebuilt once from the harness's own session snapshots, so they
show in the chat list with their messages. The events come from the same conversion a live turn
uses, so an imported turn reads as it did when it streamed, without usage, which the harness does not
keep per turn."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from apps.agents.models.agent import DEFAULT_NAME
from apps.agents.repositories.agents import agents
from apps.agents.services import titles
from apps.agents.services.paths import AGENT_ID
from apps.chat.repositories import chats
from apps.chat.services.sse import parse, to_sse

logger = logging.getLogger(__name__)

SNAPSHOT = Path("scopes/agent/default/snapshots/snapshot_latest.json")


def turns_from(messages: list[dict]) -> list[dict]:
    """One turn per message the user typed; tool results come back as user messages too, but carry
    no text, so they stay in the turn they answer."""
    found: list[dict] = []
    for msg in messages:
        content = msg.get("content") or []
        if msg.get("role") == "user" and (typed := "".join(b["text"] for b in content if isinstance(b.get("text"), str))):
            found.append({"prompt": typed, "events": []})
            continue
        if not found:
            continue
        events, seen = found[-1]["events"], set()
        stream = [{"data": b["text"]} for b in content if msg.get("role") == "assistant" and isinstance(b.get("text"), str)]
        stream += [{"current_tool_use": b["toolUse"]} for b in content if msg.get("role") == "assistant" and "toolUse" in b]
        for event in stream + [{"message": msg}]:
            if chunk := to_sse(event, seen):
                events.extend(parse(chunk))
    return found


def _read(folder: Path) -> tuple[list[dict], datetime] | None:
    try:
        snapshot = json.loads((folder / SNAPSHOT).read_text())
        messages = snapshot["data"]["messages"]
        at = datetime.fromtimestamp((folder / SNAPSHOT).stat().st_mtime, UTC)
        return turns_from(messages), at
    except FileNotFoundError:
        return None
    except Exception:
        # A snapshot from another harness version or a half-written file: that chat is left out, the rest go on.
        logger.warning("Could not import the older chat in %s", folder, exc_info=True)
        return None


async def import_older_chats(engine: AsyncEngine, data_dir: Path) -> int:
    """Adds every chat that has a session folder and no stored record, so running it again adds nothing."""
    sessions = data_dir / "sessions"
    if not sessions.is_dir():
        return 0
    added = 0
    async with async_sessionmaker(engine)() as db:
        known = set((await db.execute(sa.select(agents.c.id))).scalars())
        for agent_dir in sorted(sessions.iterdir()):
            # Folders of deleted agents or anything that is not an agent id are not chats of anyone's.
            if agent_dir.name not in known or not AGENT_ID.fullmatch(agent_dir.name):
                continue
            stored = await chats.ids_for(db, agent_dir.name)
            for folder in sorted((agent_dir / "session").glob("*")):
                if folder.name in stored or not AGENT_ID.fullmatch(folder.name):
                    continue
                read = await asyncio.to_thread(_read, folder)
                if not read or not read[0]:
                    continue
                turns, at = read
                title = titles.provisional(turns[0]["prompt"])
                await chats.seen(db, agent_dir.name, folder.name, "New chat" if title == DEFAULT_NAME else title, at)
                for t in turns:
                    turn_id = uuid4().hex
                    await chats.add_turn(db, {"id": turn_id, "agent_id": agent_dir.name, "chat_id": folder.name, "prompt": t["prompt"], "started_at": at})
                    await chats.add_events(db, turn_id, [(i, e, d) for i, (e, d) in enumerate(t["events"])])
                    await chats.end_turn(db, turn_id, "done", None, False, at)
                # One commit per chat, so a later failure keeps the chats before it.
                await db.commit()
                added += 1
    return added
