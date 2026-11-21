"""A whole turn against the real runner and real jails, with a scripted model in place of a
provider: run with `docker compose --profile test run --rm api-test`."""

import pytest

from tests.chat.test_turns import parse, use_model
from tests.helpers.scripted_model import ScriptedModel

pytestmark = pytest.mark.stack


def test_turn_edits_and_commits_in_the_jail(client, monkeypatch):
    ws = client.post("/api/workspaces").json()["data"]["id"]
    client.put(f"/api/workspaces/{ws}/file", json={"path": "AGENTS.md", "content": "Use tabs.\n"})
    model = ScriptedModel([
        [("tool", "write", {"path": f"/data/workspaces/{ws}/hello.txt", "content": "hello\n"})],
        [("tool", "shell", {"command": "git add -A && git commit -qm hello && git log --oneline | wc -l"})],
        [("text", "Committed.")],
    ])
    use_model(monkeypatch, model)
    chat = client.post(f"/api/workspaces/{ws}/chats").json()["data"]["id"]

    events = parse(client.post(f"/api/workspaces/{ws}/chats/{chat}/turns", json={"prompt": "go"}).text)

    assert [e for e, _ in events] == ["tool", "tool", "text", "done"]
    assert client.get(f"/api/workspaces/{ws}/file?path=hello.txt").json()["data"]["content"] == "hello\n"
    assert client.get(f"/api/workspaces/{ws}/git/status").json()["data"] == []
    # The environment plugin read AGENTS.md through the jail and gave it to the model.
    assert "Use tabs." in str(model.first_messages)
