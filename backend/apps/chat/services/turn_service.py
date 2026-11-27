"""Runs agent turns in the api process, not in the request that started them, so a turn goes on
whether or not a page is reading it. Each running turn keeps what it has shown in memory, so any
page can attach and replay it from the start, and queues the same events to be stored."""

import asyncio
import json
import logging
import threading
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from strands import Agent

from apps.agents.services.knowledge_service import changed_skills
from apps.chat.repositories import chats
from apps.chat.services.delegation import Delegation
from apps.chat.services.recorder import Writer
from apps.chat.services.sse import done_data, message, parse, to_sse
from core.request_id import current

logger = logging.getLogger(__name__)

# Path to checksum of every file under the workspace's skills folder.
Snapshot = Callable[[], Awaitable[dict[str, str]]]
# Work that runs beside a turn and may report one event, such as naming a new workspace.
SideTask = Callable[[], Awaitable[str | None]]

# What one turn keeps and stores. Past either, only the events that end it are kept, so a runaway
# turn cannot fill memory or the database; the live stream still shows everything.
MAX_EVENTS = 5000
MAX_EVENT_BYTES = 2_000_000
ENDING_EVENTS = {"done", "error", "stopped"}
# Not part of the chat: the workspace's new name, which the sidebar shows.
UNSTORED_EVENTS = {"title"}
# How often a running turn's new events are handed to the writer.
FLUSH_SECONDS = 1.0
FLUSH_EVENTS = 50
# How long shutdown waits for interrupted turns to wind down.
SHUTDOWN_SECONDS = 10


@dataclass(eq=False)
class LiveTurn:
    id: str
    agent_id: str
    chat_id: str
    user_id: str
    prompt: str
    model: str | None
    effort: str | None
    title: str
    started_at: datetime
    # (event, data) in order, with runs of text joined into one.
    events: list[tuple[str, dict]] = field(default_factory=list)
    status: str = "running"
    usage: dict | None = None
    truncated: bool = False
    ended_at: datetime | None = None
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    cancel: threading.Event = field(default_factory=threading.Event)
    task: asyncio.Task | None = None
    side: list[asyncio.Task] = field(default_factory=list)
    # Why the turn was ended from outside: "stopped" by a user or "interrupted" by shutdown.
    ended_by: str | None = None
    ended: asyncio.Event = field(default_factory=asyncio.Event)
    _bytes: int = 0
    # The first event changed since the last flush.
    _dirty: int = 0

    @property
    def chat_key(self) -> str:
        return f"{self.agent_id}/{self.chat_id}"

    @property
    def running(self) -> bool:
        return self.status == "running"

    def add(self, event: str, data: dict) -> None:
        if event in UNSTORED_EVENTS:
            return
        size = len(json.dumps(data))
        if event not in ENDING_EVENTS and (len(self.events) >= MAX_EVENTS or self._bytes + size > MAX_EVENT_BYTES):
            self.truncated = True
            return
        self._bytes += size
        last = self.events[-1] if self.events else None
        if event == "text" and last and last[0] == "text":
            # A new dict, since one already handed to the writer may not have been written yet.
            self.events[-1] = ("text", {"text": last[1]["text"] + data["text"]})
            self._dirty = min(self._dirty, len(self.events) - 1)
        else:
            self.events.append((event, data))

    def take_dirty(self) -> list[tuple[int, str, dict]]:
        rows = [(seq, e, d) for seq, (e, d) in enumerate(self.events) if seq >= self._dirty]
        self._dirty = len(self.events)
        return rows

    def stored(self) -> dict:
        """The turn as the chat API returns a stored one."""
        return {
            "id": self.id, "prompt": self.prompt, "model": self.model, "effort": self.effort, "status": self.status,
            "usage": self.usage, "truncated": self.truncated, "started_at": self.started_at, "ended_at": self.ended_at,
            "events": [{"event": e, "data": d} for e, d in self.events],
        }


# Turns by id, from start until their end is stored, so a page attaching in between still finds them.
# shortcut: in memory and per process, so it only holds with one api worker; move to a shared lock and a shared event log when the api runs more than one.
_live: dict[str, LiveTurn] = {}
# Turns running per user id, bounded by the max_running_turns setting.
_running: dict[str, int] = {}


def live(turn_id: str) -> LiveTurn | None:
    return _live.get(turn_id)


def live_in(agent_id: str, chat_id: str | None = None) -> list[LiveTurn]:
    """Live turns of an agent, or of one of its chats, oldest first."""
    found = [t for t in _live.values() if t.agent_id == agent_id and (chat_id is None or t.chat_id == chat_id)]
    return sorted(found, key=lambda t: t.started_at)


def is_busy(chat_key: str) -> bool:
    return any(t.chat_key == chat_key and t.running for t in _live.values())


def agent_busy(agent_id: str) -> bool:
    """Whether any chat of the agent has a turn in progress, or one whose record is still being stored."""
    return any(t.agent_id == agent_id for t in _live.values())


def can_start(user_id: str, limit: int) -> bool:
    return _running.get(user_id, 0) < limit


def _release(user_id: str) -> None:
    _running[user_id] -= 1
    if not _running[user_id]:
        del _running[user_id]


def too_many_turns_message(limit: int) -> str:
    return f"You already have {limit} turns running, the most at once. Wait for one to finish."


async def _hashes(snapshot: Snapshot | None) -> dict[str, str] | None:
    if snapshot is None:
        return None
    try:
        return await snapshot()
    except Exception:
        # Only the Learned line depends on it, so a failure leaves that out and the turn goes on.
        logger.warning("Could not read the skills' checksums", exc_info=True)
        return None


async def _run(
    make_agent: Callable[[Delegation], Agent], prompt: str, timeout: int, cancel: threading.Event, queue: asyncio.Queue, snapshot: Snapshot | None
) -> None:
    seen_tools: set[str] = set()
    loop = asyncio.get_running_loop()
    # Subagents can report from the harness's background thread.
    delegation = Delegation(lambda sse: loop.call_soon_threadsafe(queue.put_nowait, sse))
    try:
        async with asyncio.timeout(timeout):
            before = await _hashes(snapshot)
            done = None
            # Leaving the block shuts the agent down, which saves pending memory.
            async with make_agent(delegation) as agent:
                async for event in agent.stream_async(prompt, cancel_signal=cancel):
                    if "result" in event:
                        # Held until the skills are compared, so done stays the last event.
                        done = done_data(event["result"], delegation.total_usage())
                    elif sse := to_sse(event, seen_tools):
                        await queue.put(sse)
                # Inside the block, so done is not held back while the agent saves its memory.
                if done is not None:
                    after = await _hashes(snapshot) if before is not None else None
                    if after is not None:
                        done["learned"] = changed_skills(before, after)
                    await queue.put(message("done", done))
    except TimeoutError:
        logger.warning("Turn stopped at its %s second limit", timeout)
        await queue.put(message("error", {"code": "turn_timeout", "message": "The turn ran past its time limit and was stopped."}))
    except Exception:
        # Provider errors can carry request bodies and paths, so the details stay in the log.
        logger.exception("Turn failed")
        await queue.put(message("error", {"code": "turn_failed", "message": "The turn failed. The server log has the details under this request id.", "request_id": current()}))
    finally:
        await queue.put(None)


async def _side(work: SideTask, queue: asyncio.Queue) -> None:
    try:
        if (sse := await work()) is not None:
            await queue.put(sse)
    except Exception:
        logger.warning("Side task of a turn failed", exc_info=True)


def start_turn(
    writer: Writer,
    agent_id: str,
    chat_id: str,
    make_agent: Callable[[Delegation], Agent],
    prompt: str,
    timeout: int,
    *,
    title: str,
    model: str | None = None,
    effort: str | None = None,
    snapshot: Snapshot | None = None,
    user_id: str = "",
    max_running: int | None = None,
    side_tasks: Sequence[SideTask] = (),
) -> LiveTurn:
    """Starts a turn that runs until it ends, is stopped or the api shuts down. Its rows are only
    queued, never awaited, so the stream starts at once."""
    # The router already refused these; nothing here awaits, so no other request gets between the check and the claim.
    if is_busy(f"{agent_id}/{chat_id}"):
        raise TurnRefused("chat_busy", "This chat already has a turn in progress.")
    if max_running is not None and not can_start(user_id, max_running):
        raise TurnRefused("too_many_turns", too_many_turns_message(max_running))
    now = datetime.now(UTC)
    turn = LiveTurn(uuid.uuid4().hex, agent_id, chat_id, user_id, prompt, model, effort, title, now)
    _live[turn.id] = turn
    _running[user_id] = _running.get(user_id, 0) + 1
    row = {"id": turn.id, "agent_id": agent_id, "chat_id": chat_id, "prompt": prompt, "model": model, "effort": effort, "started_at": now}
    writer.put(lambda db: chats.seen(db, agent_id, chat_id, title, now))
    writer.put(lambda db: chats.add_turn(db, row))
    queue: asyncio.Queue = asyncio.Queue()
    turn.task = asyncio.create_task(_run(make_agent, prompt, timeout, turn.cancel, queue, snapshot))
    # A task cancelled before it first runs never reaches _run's finally; this ends the pump anyway (a second None is skipped).
    turn.task.add_done_callback(lambda _: queue.put_nowait(None))
    # Not cancelled with the turn: each bounds its own time, and its result (a workspace's name)
    # should land even if the turn is stopped.
    turn.side = [asyncio.create_task(_side(work, queue)) for work in side_tasks]
    _pumps.add(pump := asyncio.create_task(_pump(turn, queue, writer)))
    pump.add_done_callback(_pumps.discard)
    return turn


class TurnRefused(Exception):
    def __init__(self, code: str, text: str):
        super().__init__(text)
        self.code, self.text = code, text


# Holds each turn's pump until it ends, since nothing else references it once the request is gone.
_pumps: set[asyncio.Task] = set()


def _publish(turn: LiveTurn, chunk: str) -> None:
    for event, data in parse(chunk):
        turn.add(event, data)
        if event == "done":
            turn.usage = data.get("usage")
    for q in turn.subscribers:
        q.put_nowait(chunk)


def _flush(turn: LiveTurn, writer: Writer) -> None:
    if rows := turn.take_dirty():
        writer.put(lambda db: chats.add_events(db, turn.id, rows))


async def _pump(turn: LiveTurn, queue: asyncio.Queue, writer: Writer) -> None:
    """Hands the turn's events to the pages reading it and to the writer, then records how it ended."""
    loop = asyncio.get_running_loop()
    flushed_at, pending = loop.time(), 0
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), FLUSH_SECONDS)
            except TimeoutError:
                item = ""
            if item is None:
                break
            if item:
                _publish(turn, item)
                pending += 1
            if pending and (pending >= FLUSH_EVENTS or loop.time() - flushed_at >= FLUSH_SECONDS):
                _flush(turn, writer)
                flushed_at, pending = loop.time(), 0
        if turn.ended_by == "stopped":
            _publish(turn, message("stopped", {}))
        kinds = {e for e, _ in turn.events}
        turn.status = turn.ended_by or ("done" if "done" in kinds else "failed")
    except BaseException:
        # A pump that breaks still ends the turn, so the chat is not left busy for good.
        logger.exception("Turn could not be followed to its end")
        turn.status = turn.ended_by or "failed"
        turn.cancel.set()
        if turn.task:
            turn.task.cancel()
        raise
    finally:
        turn.ended_at = datetime.now(UTC)
        _release(turn.user_id)
        # Side work still running reports before the turn closes, so its event can come after done.
        try:
            await asyncio.gather(*turn.side)
        finally:
            while not queue.empty():
                if item := queue.get_nowait():
                    _publish(turn, item)
            turn.ended.set()
            for q in turn.subscribers:
                q.put_nowait(None)
            _flush(turn, writer)
            status, usage, truncated, at = turn.status, turn.usage, turn.truncated, turn.ended_at
            writer.put(lambda db: chats.end_turn(db, turn.id, status, usage, truncated, at), then=lambda: _live.pop(turn.id, None))


async def subscribe(turn: LiveTurn) -> AsyncIterator[str]:
    """Everything the turn has shown so far, then each new event until it ends. Leaving early only
    stops reading; the turn goes on."""
    queue: asyncio.Queue = asyncio.Queue()
    # Taken and registered with no await in between, so no event is missed or sent twice.
    replay = message("turn", {"id": turn.id}) + "".join(message(e, d) for e, d in turn.events)
    if turn.ended.is_set():
        yield replay
        return
    turn.subscribers.add(queue)
    try:
        yield replay
        while (item := await queue.get()) is not None:
            yield item
    finally:
        turn.subscribers.discard(queue)


def stop(turn: LiveTurn, reason: str = "stopped") -> None:
    """Ends a running turn. Cancelling the task closes any runner request in flight, and the runner
    then kills that command's jail."""
    if not turn.running or turn.ended_by:
        return
    logger.info("Turn %s: %s", reason, turn.id)
    turn.ended_by = reason
    turn.cancel.set()
    if turn.task:
        turn.task.cancel()


async def shutdown() -> None:
    """Ends every running turn as interrupted and waits for each to record that."""
    for turn in list(_live.values()):
        stop(turn, "interrupted")
        for s in turn.side:
            s.cancel()
    if _pumps:
        await asyncio.wait(list(_pumps), timeout=SHUTDOWN_SECONDS)
