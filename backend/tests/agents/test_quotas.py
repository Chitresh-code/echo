import pytest

from apps.chat.services import turn_service
from core.config import get_settings
from tests.helpers.accounts import own, sign_in_as
from tests.helpers.turns import busy

WS = "0123456789abcdef" * 2
OTHER = "f" * 32


@pytest.fixture(autouse=True)
def _owns_ws(client, user):
    own(client, user, WS)


def code(r):
    return r.json()["error"]["code"]


def test_agent_limit(client, fake_runner, monkeypatch):
    monkeypatch.setenv("ECHO_MAX_AGENTS", "2")
    get_settings.cache_clear()
    assert client.post("/api/agents", json={"name": "Second"}).status_code == 200
    r = client.post("/api/agents", json={"name": "Third"})
    assert r.status_code == 409 and code(r) == "agent_limit_reached" and len(fake_runner.workspaces) == 1
    # Deleting one makes room again.
    client.delete(f"/api/agents/{WS}")
    assert client.post("/api/agents", json={"name": "Third"}).status_code == 200


def test_delete_removes_files_sessions_notes_and_the_row(client, fake_runner):
    data = get_settings().data_dir
    for folder in ("sessions", "memory"):
        (data / folder / WS).mkdir(parents=True)
        (data / folder / WS / "x.md").write_text("kept by the harness")
    r = client.delete(f"/api/agents/{WS}")
    assert r.json()["data"] == {"deleted": True} and fake_runner.deleted == [WS]
    assert not (data / "sessions" / WS).exists() and not (data / "memory" / WS).exists()
    assert code(client.get(f"/api/agents/{WS}")) == "agent_not_found"
    assert code(client.delete(f"/api/agents/{WS}")) == "agent_not_found"


def test_delete_someone_elses_agent_is_not_found(client, fake_runner):
    sign_in_as(client, "other-user")
    r = client.delete(f"/api/agents/{WS}")
    assert r.status_code == 404 and code(r) == "agent_not_found" and fake_runner.deleted == []


def test_delete_while_a_turn_runs_is_refused(client, fake_runner):
    with busy(WS, "b" * 32):
        r = client.delete(f"/api/agents/{WS}")
    assert r.status_code == 409 and code(r) == "agent_busy" and fake_runner.deleted == []


def test_usage_and_full_workspace_refuses_saves(client, fake_runner):
    assert client.get(f"/api/agents/{WS}/usage").json()["data"] == fake_runner.usage
    fake_runner.usage = {"used_bytes": 3000, "limit_bytes": 2000}
    r = client.put(f"/api/agents/{WS}/file", json={"path": "a.txt", "content": "hi"})
    assert r.status_code == 507 and code(r) == "disk_quota_exceeded" and fake_runner.requests == []
