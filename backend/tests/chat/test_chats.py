"""Stored chats: a turn is written in the background, survives a restart, and is read back the way
it was streamed; only the agent's owner reaches it."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from apps.chat.services import turn_service
from apps.chat.services.recorder import Writer
from core.config import get_settings
from tests.chat.test_turns import DONE, WS, parse, shell_then_done, turn, use_model
from tests.helpers.accounts import add_key, own, sign_in_as

CHAT, OTHER = "b" * 32, "d" * 32
BASE = f"/api/agents/{WS}/chats"


def data(r):
    assert r.status_code == 200, r.text
    return r.json()["data"]


def send(client, user, chat=CHAT, prompt="say hi"):
    r = client.post(f"{BASE}/{chat}/turns", json=turn(prompt, add_key(client, user)))
    assert r.status_code == 200
    return parse(r.text)


def app_client():
    from main import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


def test_a_chat_is_stored_and_read_back_after_a_restart(monkeypatch, fake_runner):
    use_model(monkeypatch, shell_then_done())
    fake_runner.lines = [DONE]
    with app_client() as client:
        user = sign_in_as(client)
        own(client, user, WS)
        streamed = send(client, user)
        turn_id = streamed[0][1]["id"]
        cookies = dict(client.cookies)

    # Leaving the app drains the writer; a fresh one reads only the database.
    with app_client() as client:
        client.cookies.update(cookies)
        listed = data(client.get(BASE))
        assert [(c["id"], c["title"], c["running"]) for c in listed["chats"]] == [(CHAT, "say hi", False)] and not listed["more"]
        chat = data(client.get(f"{BASE}/{CHAT}"))
        [stored] = chat["turns"]
        assert stored["id"] == turn_id and stored["prompt"] == "say hi" and stored["status"] == "done" and stored["model"] == "anthropic/claude-sonnet-5-5"
        assert stored["usage"] == streamed[-1][1]["usage"]
        # Text runs are joined, so the stored events read as the same chat with fewer events.
        events = [(e["event"], e["data"]) for e in stored["events"]]
        text = lambda evs: "".join(d["text"] for e, d in evs if e == "text")
        assert text(events) == text(streamed[1:]) and [e for e, _ in events if e != "text"] == [e for e, _ in streamed[1:] if e != "text"]
        replay = client.get(f"{BASE}/{CHAT}/turns/{turn_id}/events")
        assert replay.headers["content-type"].startswith("text/event-stream") and parse(replay.text)[0] == ("turn", {"id": turn_id})
        assert client.post(f"{BASE}/{CHAT}/turns/{turn_id}/stop").json()["data"] == {"stopping": False}


def test_delete_removes_the_chat_and_its_session_folders(monkeypatch, fake_runner):
    use_model(monkeypatch, shell_then_done())
    fake_runner.lines = [DONE]
    with app_client() as client:
        user = sign_in_as(client)
        own(client, user, WS)
        send(client, user)
        sessions = get_settings().data_dir / "sessions" / WS
        assert (sessions / "session" / CHAT).is_dir()
        # The end of the turn is written in the background; wait for it, as a page would.
        client.portal.call(lambda: asyncio.wait_for(client.app.state.chat_writer._queue.join(), 5))
        assert client.delete(f"{BASE}/{CHAT}").json()["data"] == {"deleted": True}
        assert not (sessions / "session" / CHAT).exists() and not (sessions / "context" / CHAT).exists()
        assert data(client.get(BASE))["chats"] == []
        assert client.get(f"{BASE}/{CHAT}").json()["error"]["code"] == "chat_not_found"
        assert client.delete(f"{BASE}/{CHAT}").status_code == 404


def test_a_chat_with_a_live_turn_cannot_be_deleted_and_shows_running(client, user, fake_runner):
    own(client, user, WS)
    from tests.helpers.turns import busy

    with busy(WS, CHAT):
        assert client.delete(f"{BASE}/{CHAT}").json()["error"]["code"] == "chat_busy"
        # Not yet written, but listed and opened from memory.
        assert [(c["id"], c["running"]) for c in data(client.get(BASE))["chats"]] == [(CHAT, True)]
        assert data(client.get(f"{BASE}/{CHAT}"))["running"] is True


def test_another_agents_chat_is_not_found(monkeypatch, fake_runner):
    use_model(monkeypatch, shell_then_done())
    fake_runner.lines = [DONE]
    with app_client() as client:
        user = sign_in_as(client)
        own(client, user, WS)
        own(client, user, OTHER)
        turn_id = send(client, user)[0][1]["id"]
        client.portal.call(lambda: asyncio.wait_for(client.app.state.chat_writer._queue.join(), 5))
        other = f"/api/agents/{OTHER}/chats/{CHAT}"
        assert client.get(other).json()["error"]["code"] == "chat_not_found"
        assert client.get(f"{other}/turns/{turn_id}/events").json()["error"]["code"] == "turn_not_found"
        assert client.post(f"{other}/turns/{turn_id}/stop").status_code == 404
        assert data(client.get(f"/api/agents/{OTHER}/chats"))["chats"] == []


@pytest.mark.parametrize("method, path, code", [
    ("GET", f"{BASE}/not-hex", "invalid_chat_id"),
    ("DELETE", f"{BASE}/{'B' * 32}", "invalid_chat_id"),
    ("GET", f"{BASE}/{CHAT}/turns/zz/events", "invalid_turn_id"),
    ("POST", f"{BASE}/{CHAT}/turns/zz/stop", "invalid_turn_id"),
    ("GET", f"{BASE}?before=..", "invalid_chat_id"),
    ("GET", f"{BASE}/{CHAT}/turns/{'e' * 32}/events", "turn_not_found"),
])
def test_bad_or_unknown_ids_are_refused(client, user, fake_runner, method, path, code):
    own(client, user, WS)
    assert client.request(method, path).json()["error"]["code"] == code


def test_chats_page_newest_first(client, user, fake_runner):
    from apps.chat.repositories import chats
    from apps.chat.services import chat_service

    own(client, user, WS)
    start = datetime(2026, 1, 1, tzinfo=UTC)

    async def fill(db):
        for i in range(chat_service.CHATS_PAGE + 2):
            await chats.seen(db, WS, f"{i:032x}", f"chat {i}", start + timedelta(minutes=i))

    client.app.state.chat_writer.put(fill)
    client.portal.call(lambda: asyncio.wait_for(client.app.state.chat_writer._queue.join(), 5))
    first = data(client.get(BASE))
    assert first["more"] and len(first["chats"]) == chat_service.CHATS_PAGE and first["chats"][0]["title"] == f"chat {chat_service.CHATS_PAGE + 1}"
    rest = data(client.get(BASE, params={"before": first["chats"][-1]["id"]}))
    assert [c["title"] for c in rest["chats"]] == ["chat 1", "chat 0"] and not rest["more"]


async def test_the_writer_retries_a_locked_database_in_order(monkeypatch):
    real_sleep = asyncio.sleep
    waits = []
    # Only the writer's retry wait is cut short; patching asyncio itself would reach every thread.
    monkeypatch.setattr(asyncio, "sleep", lambda s, *a: waits.append(s) or real_sleep(0))
    written, failures = [], [OperationalError("x", {}, Exception("database is locked"))]

    def write(n):
        async def go(db):
            if failures and n == 1:
                raise failures.pop()
            written.append(n)
        return go

    writer = Writer(object())
    writer._sessions = lambda: _NoDb()
    writer.start()
    done = []
    for n in (1, 2):
        writer.put(write(n), then=lambda n=n: done.append(n))
    await writer.stop()
    # The failed batch is written again whole, so 1 is first both times and nothing is lost.
    assert written == [1, 2] and done == [1, 2] and waits[:1] == [1]


async def test_a_write_that_can_never_succeed_is_dropped_and_the_rest_go_on():
    written = []

    async def bad(db):
        raise ValueError("chat deleted meanwhile")

    async def good(db):
        written.append("good")

    writer = Writer(object())
    writer._sessions = lambda: _NoDb()
    writer.start()
    writer.put(bad)
    await writer.stop()
    writer.start()
    writer.put(good)
    await writer.stop()
    assert written == ["good"]


class _NoDb:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        pass


def test_a_stalled_writer_never_delays_the_stream(monkeypatch, fake_runner):
    use_model(monkeypatch, shell_then_done())
    fake_runner.lines = [DONE]
    with app_client() as client:
        user = sign_in_as(client)
        own(client, user, WS)
        key = add_key(client, user)
        writer = client.app.state.chat_writer
        release = asyncio.Event()
        real = writer._write

        async def stalled(batch):
            # As a database locked for the whole turn would leave it.
            await release.wait()
            await real(batch)

        writer._write = stalled
        r = client.post(f"{BASE}/{CHAT}/turns", json=turn("hi", key))
        assert parse(r.text)[-1][0] == "done"
        # Nothing is written yet, and the chat still reads in full from memory.
        assert data(client.get(f"{BASE}/{CHAT}"))["turns"][0]["status"] == "done"
        client.portal.call(release.set)
        client.portal.call(lambda: asyncio.wait_for(writer._queue.join(), 5))
        assert data(client.get(BASE))["chats"][0]["id"] == CHAT


def test_turns_left_running_are_interrupted_at_startup(monkeypatch, fake_runner):
    with app_client() as client:
        user = sign_in_as(client)
        own(client, user, WS)
        cookies = dict(client.cookies)
        now = datetime.now(UTC)
        from apps.chat.repositories import chats

        async def left_running(db):
            await chats.seen(db, WS, CHAT, "hi", now)
            await chats.add_turn(db, {"id": "e" * 32, "agent_id": WS, "chat_id": CHAT, "prompt": "hi", "started_at": now})

        client.app.state.chat_writer.put(left_running)
    with app_client() as client:
        client.cookies.update(cookies)
        assert data(client.get(f"{BASE}/{CHAT}"))["turns"][0]["status"] == "interrupted"


def test_deleting_the_agent_removes_its_chats(monkeypatch, fake_runner):
    with app_client() as client:
        user = sign_in_as(client)
        own(client, user, WS)
        from apps.chat.repositories import chats

        async def fill(db):
            await chats.seen(db, WS, CHAT, "hi", datetime.now(UTC))

        client.app.state.chat_writer.put(fill)
        client.portal.call(lambda: asyncio.wait_for(client.app.state.chat_writer._queue.join(), 5))
        assert client.delete(f"/api/agents/{WS}").status_code in (200, 204)
    db = sqlite3.connect(get_settings().data_dir / "echo.db")
    assert db.execute("select count(*) from chats").fetchone() == (0,)
