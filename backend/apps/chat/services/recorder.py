"""Writes chats, turns and their events to the database in the background, so storing a chat never
slows a turn down. A turn only queues its writes; one writer per process drains the queue in
batches, in order. Running turns are read from memory, so nothing waits for the writer to catch up."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

Write = Callable[[AsyncSession], Awaitable[None]]

# Commands written in one transaction at most, so one busy turn cannot hold the database for long.
BATCH = 500
# A locked or unavailable database is retried with growing waits, up to this many seconds.
MAX_RETRY_WAIT = 30
# How long shutdown waits for queued writes before giving up on them.
DRAIN_SECONDS = 10


class Writer:
    def __init__(self, engine: AsyncEngine):
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        # Unbounded so putting never waits; each turn's events are capped before they get here.
        self._queue: asyncio.Queue[tuple[Write, Callable[[], None] | None]] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    def put(self, write: Write, then: Callable[[], None] | None = None) -> None:
        """Queues a write; `then` runs once it is committed, or given up on."""
        self._queue.put_nowait((write, then))

    async def _loop(self) -> None:
        while True:
            batch = [await self._queue.get()]
            while len(batch) < BATCH and not self._queue.empty():
                batch.append(self._queue.get_nowait())
            await self._write(batch)
            for _, then in batch:
                if then:
                    then()
                self._queue.task_done()

    async def _write(self, batch) -> None:
        wait = 1
        while True:
            try:
                async with self._sessions() as db:
                    for write, _ in batch:
                        await write(db)
                    await db.commit()
                return
            except OperationalError:
                # Locked, full or briefly unreadable: the same batch again, so order is kept.
                logger.warning("Could not store chat history, retrying in %s s", wait, exc_info=True)
                await asyncio.sleep(wait)
                wait = min(wait * 2, MAX_RETRY_WAIT)
            except Exception:
                # A write that can never succeed (its chat was deleted meanwhile) must not block the rest.
                logger.exception("Dropped %s chat history writes that cannot be stored", len(batch))
                return

    async def stop(self) -> None:
        """Writes what is queued, waiting at most DRAIN_SECONDS, then stops."""
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), DRAIN_SECONDS)
        except TimeoutError:
            logger.warning("Stopped with %s chat history writes not stored", self._queue.qsize())
        self._task.cancel()
