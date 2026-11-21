"""Runs one agent turn and streams it. The agent runs in its own task that feeds a queue, so the
turn time limit and a client disconnect can both stop it cleanly, wherever the stream is waiting."""

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable

from strands import Agent

from apps.agents.services.knowledge_service import changed_skills
from apps.chat.services.delegation import Delegation
from apps.chat.services.sse import done_data, message, to_sse
from core.request_id import current

logger = logging.getLogger(__name__)

# Chats with a turn in progress. A chat is claimed until its agent task has fully ended, so two
# turns never write the same session at once.
# shortcut: in memory and per process, so it only holds with one api worker; move to a shared lock when the api runs more than one.
_busy: set[str] = set()
# Turns running per user id, bounded by the max_running_turns setting.
_running: dict[str, int] = {}
# Path to checksum of every file under the workspace's skills folder.
Snapshot = Callable[[], Awaitable[dict[str, str]]]


def is_busy(chat_key: str) -> bool:
    return chat_key in _busy


def agent_busy(agent_id: str) -> bool:
    """Whether any chat of the agent has a turn in progress. Chat keys are `agent_id/chat_id`."""
    return any(key.startswith(f"{agent_id}/") for key in _busy)


def can_start(user_id: str, limit: int) -> bool:
    return _running.get(user_id, 0) < limit


def _release(chat_key: str, user_id: str) -> None:
    _busy.discard(chat_key)
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


async def stream_turn(
    chat_key: str,
    make_agent: Callable[[Delegation], Agent],
    prompt: str,
    timeout: int,
    snapshot: Snapshot | None = None,
    user_id: str = "",
    max_running: int | None = None,
) -> AsyncIterator[str]:
    # The router already refused these; the checks here cover requests racing past it.
    if chat_key in _busy:
        yield message("error", {"code": "chat_busy", "message": "This chat already has a turn in progress."})
        return
    if max_running is not None and not can_start(user_id, max_running):
        yield message("error", {"code": "too_many_turns", "message": too_many_turns_message(max_running)})
        return
    _busy.add(chat_key)
    _running[user_id] = _running.get(user_id, 0) + 1
    cancel = threading.Event()
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_run(make_agent, prompt, timeout, cancel, queue, snapshot))
    # Released only once the agent task has fully ended, however the turn ended.
    task.add_done_callback(lambda _: _release(chat_key, user_id))
    try:
        while (item := await queue.get()) is not None:
            yield item
    finally:
        # Reached when the turn ends and when the client goes away. Cancelling the task closes any
        # runner request in flight, and the runner then kills that command's jail.
        if not task.done():
            logger.info("Turn cancelled before it finished")
        cancel.set()
        task.cancel()
