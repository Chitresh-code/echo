"""Turns without a database: a writer that only records what it was given, and a way to make a
chat look busy."""

from contextlib import contextmanager
from datetime import UTC, datetime

from apps.chat.services import turn_service


class FakeWriter:
    def __init__(self):
        self.writes = []

    def put(self, write, then=None):
        self.writes.append(write)
        if then:
            then()


@contextmanager
def busy(agent_id: str, chat_id: str, user_id: str = "someone"):
    turn = turn_service.LiveTurn("f" * 32, agent_id, chat_id, user_id, "hi", None, None, "hi", datetime.now(UTC))
    turn_service._live[turn.id] = turn
    try:
        yield turn
    finally:
        turn_service._live.pop(turn.id, None)
