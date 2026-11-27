import time

import sqlalchemy as sa
from fastapi.testclient import TestClient

from apps.accounts.repositories.users import users
from apps.usage.repositories.usage import usage
from tests.chat.test_turns import CHAT, DONE, TURNS, WS, parse, turn, use_model
from tests.helpers.accounts import _run, add_key, own, sign_in_as
from tests.helpers.scripted_model import ScriptedModel


def rows(client):
    async def work(db):
        return [dict(r) for r in (await db.execute(sa.select(usage))).mappings()]

    return _run(client, work)


def settled_rows(client):
    """The ledger once the turn has ended: it is written after the reply, when side work is done."""
    deadline = time.monotonic() + 5
    while not (found := rows(client)) and time.monotonic() < deadline:
        time.sleep(0.02)
    return found


def test_a_turn_records_what_every_call_used_and_outlives_its_workspace_and_key(monkeypatch, fake_runner):
    from main import create_app

    model = ScriptedModel([[("tool", "shell", {"command": "ls"})], [("text", "Done.")]], usage={"inputTokens": 1000, "outputTokens": 50})
    model.config["model_id"] = "claude-haiku-5-5"
    use_model(monkeypatch, model)
    fake_runner.lines = [DONE]
    with TestClient(create_app()) as client:
        user = sign_in_as(client)
        own(client, user, WS)
        key = add_key(client, user)
        events = parse(client.post(TURNS, json=turn("hi", key, "claude-haiku-5-5")).text)
        done = events[-1][1]["usage"]
        [row] = settled_rows(client)
        # Two agent calls, plus any side work the turn did after the reply, all on the one model.
        assert row["calls"] >= 2 and row["input_tokens"] == 1000 * row["calls"] and row["cost_micros"] > 0
        assert (row["user_id"], row["agent_id"], row["chat_id"], row["credential_id"], row["model"]) == (user, WS, CHAT, key, "claude-haiku-5-5")
        assert done["inputTokens"] >= 2000 and done["costMicros"] > 0 and done["unpriced"] is False
        # The stored turn carries the final count, which can include work done after the reply.
        turn_usage = client.get(f"/api/agents/{WS}/chats/{CHAT}").json()["data"]["turns"][0]["usage"]
        assert turn_usage["inputTokens"] == row["input_tokens"] and turn_usage["costMicros"] == row["cost_micros"]

        assert client.delete(f"/api/credentials/{key}").status_code == 200
        assert client.delete(f"/api/agents/{WS}").status_code == 200
        assert len(rows(client)) == 1

        async def delete_user(db):
            await db.execute(users.delete().where(users.c.id == user))

        _run(client, delete_user)
        assert rows(client) == []
