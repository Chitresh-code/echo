"""Workspaces started without a name: the provisional name from the first message, the side
model's title, and the `title` event."""

import asyncio
import logging

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.agents.repositories import agents
from apps.agents.services import titles
from tests.chat.test_turns import DONE, parse, turn, use_model
from tests.helpers.accounts import add_key
from tests.helpers.scripted_model import ScriptedModel

PROMPT = "Match the **Stripe** payouts for October to the [ledger](https://example.com/l) and flag anything that does not add up"


@pytest.mark.parametrize("prompt, name", [
    ("Fix the login bug", "Fix the login bug"),
    ("# Report\n\n- one\n- two\n\n```py\nx = 1\n```", "Report one two x = 1"),
    (PROMPT, "Match the Stripe payouts for October to the ledger and flag…"),
    ("x" * 200, "x" * 59 + "…"),
    ("   \n```\n```  ", "New workspace"),
    ("tab\there\x00and​zero", "tab here and zero"),
])
def test_provisional(prompt, name):
    assert titles.provisional(prompt) == name
    assert len(titles.provisional(prompt)) <= titles.PROVISIONAL_CHARS


@pytest.mark.parametrize("reply, title", [
    ('"Stripe payout reconciliation."', "Stripe payout reconciliation"),
    ("Title: **Login bug fix**\nThis title covers...", "Login bug fix"),
    ("\n\n  Weekly report  \n", "Weekly report"),
    ("bad\x1b[31mcolour", "bad [31mcolour"),
    ('""', None),
    ("", None),
])
def test_clean(reply, title):
    assert titles.clean(reply) == title


def test_a_long_title_is_cut_at_a_word():
    got = titles.clean("word " * 40)
    assert len(got) <= titles.TITLE_CHARS and got.endswith("word…")


class Failing(ScriptedModel):
    async def stream(self, *args, **kwargs):
        raise RuntimeError(f"provider said no to: {PROMPT}")
        yield


class Slow(ScriptedModel):
    async def stream(self, *args, **kwargs):
        await asyncio.sleep(5)
        yield {}


def test_generate():
    assert asyncio.run(titles.generate(ScriptedModel([[("text", "Payout check.")]]), PROMPT)) == "Payout check"


def test_generate_gives_up_quietly(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    assert asyncio.run(titles.generate(Failing([]), PROMPT)) is None
    assert "RuntimeError" in caplog.text and "Stripe" not in caplog.text
    monkeypatch.setattr(titles, "TITLE_TIMEOUT", 0.05)
    assert asyncio.run(titles.generate(Slow([]), PROMPT)) is None


# Through the turn route


def start(monkeypatch, client, user, fake_runner, title):
    """A workspace made with no name, and the route to send its turns. `title` stands in for the
    side model's answer."""
    calls = []

    async def generate(side_model, prompt):
        calls.append(prompt)
        return await title() if callable(title) else title

    monkeypatch.setattr(titles, "generate", generate)
    use_model(monkeypatch, ScriptedModel([[("text", "On it.")]]))
    fake_runner.lines = [DONE]
    agent_id = client.post("/api/agents", json={}).json()["data"]["id"]
    key = add_key(client, user)
    return agent_id, lambda prompt: parse(client.post(f"/api/agents/{agent_id}/chats/{'b' * 32}/turns", json=turn(prompt, key)).text), calls


def name_of(client, agent_id):
    return client.get(f"/api/agents/{agent_id}").json()["data"]["name"]


def test_the_first_turn_names_the_workspace(monkeypatch, client, user, fake_runner):
    agent_id, send, calls = start(monkeypatch, client, user, fake_runner, "Stripe payout check")
    events = send(PROMPT)
    assert ("title", {"name": "Stripe payout check"}) in events and [e for e, _ in events].count("title") == 1
    assert "done" in [e for e, _ in events]
    assert name_of(client, agent_id) == "Stripe payout check" and calls == [PROMPT]
    # Only once: a later turn, or a new chat in it, leaves the name alone.
    events = send("and September too")
    assert "title" not in [e for e, _ in events] and calls == [PROMPT]


def test_without_a_title_the_provisional_name_stays(monkeypatch, client, user, fake_runner):
    agent_id, send, _ = start(monkeypatch, client, user, fake_runner, None)
    events = send(PROMPT)
    assert "title" not in [e for e, _ in events] and events[-1][0] == "done"
    assert name_of(client, agent_id) == titles.provisional(PROMPT)


def test_a_rename_during_the_turn_wins(monkeypatch, app, client, user, fake_runner):
    async def rename_first():
        # The user renames the workspace while the title is still being written.
        async with async_sessionmaker(app.state.db_engine)() as db:
            await agents.update(db, agent_id, user, {"name": "My name"})
            await db.commit()
        return "Model's title"

    agent_id, send, _ = start(monkeypatch, client, user, fake_runner, rename_first)
    events = send(PROMPT)
    assert "title" not in [e for e, _ in events] and events[-1][0] == "done"
    assert name_of(client, agent_id) == "My name"


def test_a_failing_title_does_not_fail_the_turn(monkeypatch, client, user, fake_runner):
    async def boom():
        raise RuntimeError("nope")

    agent_id, send, _ = start(monkeypatch, client, user, fake_runner, boom)
    assert send(PROMPT)[-1][0] == "done"
    assert name_of(client, agent_id) == titles.provisional(PROMPT)


def test_a_named_workspace_is_never_titled(monkeypatch, client, user, fake_runner):
    agent_id, send, calls = start(monkeypatch, client, user, fake_runner, "Title")
    client.patch(f"/api/agents/{agent_id}", json={"name": "Chosen"})
    assert "title" not in [e for e, _ in send(PROMPT)] and calls == []
    assert name_of(client, agent_id) == "Chosen"


def test_rename_if_is_scoped_to_the_owner(app, client, user, fake_runner):
    agent_id = client.post("/api/agents", json={}).json()["data"]["id"]

    async def work():
        async with async_sessionmaker(app.state.db_engine)() as db:
            assert not await agents.rename_if(db, agent_id, "someone-else", "New workspace", "Taken")
            assert not await agents.rename_if(db, agent_id, user, "Other name", "Taken")
            assert await agents.rename_if(db, agent_id, user, "New workspace", "Mine")
            await db.commit()

    client.portal.call(work)
    assert name_of(client, agent_id) == "Mine"
