"""Runs one agent turn and streams it. The agent runs in its own task that feeds a queue, so the
turn time limit and a client disconnect can both stop it cleanly, wherever the stream is waiting."""

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Callable

from strands import Agent

from apps.chat.services.sse import message, to_sse
from core.request_id import current

logger = logging.getLogger(__name__)

# Chats with a turn in progress. A chat is claimed until its agent task has fully ended, so two
# turns never write the same session at once.
# shortcut: in memory and per process, so it only holds with one api worker; move to a shared lock when the api runs more than one.
_busy: set[str] = set()


def is_busy(chat_key: str) -> bool:
    return chat_key in _busy


async def _run(make_agent: Callable[[], Agent], prompt: str, timeout: int, cancel: threading.Event, queue: asyncio.Queue) -> None:
    seen_tools: set[str] = set()
    try:
        async with asyncio.timeout(timeout):
            # Leaving the block shuts the agent down, which saves pending memory.
            async with make_agent() as agent:
                async for event in agent.stream_async(prompt, cancel_signal=cancel):
                    if sse := to_sse(event, seen_tools):
                        await queue.put(sse)
    except TimeoutError:
        logger.warning("Turn stopped at its %s second limit", timeout)
        await queue.put(message("error", {"code": "turn_timeout", "message": "The turn ran past its time limit and was stopped."}))
    except Exception:
        # Provider errors can carry request bodies and paths, so the details stay in the log.
        logger.exception("Turn failed")
        await queue.put(message("error", {"code": "turn_failed", "message": "The turn failed. The server log has the details under this request id.", "request_id": current()}))
    finally:
        await queue.put(None)


async def stream_turn(chat_key: str, make_agent: Callable[[], Agent], prompt: str, timeout: int) -> AsyncIterator[str]:
    # The router already refused a busy chat; this check covers two requests racing past it.
    if chat_key in _busy:
        yield message("error", {"code": "chat_busy", "message": "This chat already has a turn in progress."})
        return
    _busy.add(chat_key)
    cancel = threading.Event()
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_run(make_agent, prompt, timeout, cancel, queue))
    task.add_done_callback(lambda _: _busy.discard(chat_key))
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
