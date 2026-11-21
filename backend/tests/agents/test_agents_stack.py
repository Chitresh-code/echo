"""Against the real runner and real jails: run with `docker compose --profile test run --rm api-test`."""

import asyncio
import base64

import pytest

from core.config import get_settings
from sandbox.runner_sandbox import RunnerSandbox

pytestmark = pytest.mark.stack


def data(r):
    assert r.status_code == 200, r.text
    return r.json()["data"]


@pytest.fixture
def ws(client):
    return data(client.post("/api/agents", json={"name": "Test agent"}))["id"]


def save(client, ws, path, content):
    return data(client.put(f"/api/agents/{ws}/file", json={"path": path, "content": content}))


def run(ws, command):
    # There is no route that runs a command, so setup such as commits goes through the sandbox.
    return asyncio.run(RunnerSandbox(ws, get_settings().runner_socket, 60).execute(command))


def test_new_agent_is_listed_and_has_skills_folder(client, ws):
    assert ws in [a["id"] for a in data(client.get("/api/agents"))]
    tree = data(client.get(f"/api/agents/{ws}/tree"))
    assert {"path": ".agent/skills", "type": "dir"} in tree["entries"] and tree["truncated"] is False
    assert not any(e["path"] == ".git" or e["path"].startswith(".git/") for e in tree["entries"])


def test_tree_cap(client, ws, monkeypatch):
    from apps.agents.services import agent_service

    monkeypatch.setattr(agent_service, "MAX_TREE_ENTRIES", 3)
    for i in range(5):
        save(client, ws, f"f{i}.txt", "x")
    tree = data(client.get(f"/api/agents/{ws}/tree"))
    assert len(tree["entries"]) == 3 and tree["truncated"] is True


def test_save_then_read_including_nested_and_odd_names(client, ws):
    save(client, ws, "src/deep/my file.py", "print('hi')\n")
    save(client, ws, "-dash.txt", "dash")
    assert data(client.get(f"/api/agents/{ws}/file", params={"path": "src/deep/my file.py"}))["content"] == "print('hi')\n"
    assert data(client.get(f"/api/agents/{ws}/file", params={"path": "-dash.txt"}))["content"] == "dash"
    paths = {e["path"] for e in data(client.get(f"/api/agents/{ws}/tree"))["entries"]}
    assert {"src", "src/deep", "src/deep/my file.py", "-dash.txt"} <= paths


def test_large_save_round_trips(client, ws):
    content = "line of text\n" * 40_000  # about 500 KB, past the 128 KB argument limit
    save(client, ws, "big.txt", content)
    assert data(client.get(f"/api/agents/{ws}/file", params={"path": "big.txt"}))["content"] == content


def test_binary_file_reads_as_base64(client, ws):
    assert run(ws, "printf '\\377\\000\\001' > bin.dat").exit_code == 0
    got = data(client.get(f"/api/agents/{ws}/file", params={"path": "bin.dat"}))
    assert got["encoding"] == "base64" and base64.b64decode(got["content"]) == b"\xff\x00\x01"


def test_missing_file_and_directory(client, ws):
    assert client.get(f"/api/agents/{ws}/file", params={"path": "nope"}).status_code == 404
    assert client.get(f"/api/agents/{ws}/file", params={"path": ".agent"}).json()["error"]["code"] == "is_a_directory"


def test_symlink_out_of_the_agents_workspace_reads_nothing_secret(client, ws):
    run(ws, "ln -s /etc/shadow shadow; ln -s /data/workspaces sibling")
    assert client.get(f"/api/agents/{ws}/file", params={"path": "shadow"}).status_code in (403, 404)
    r = client.get(f"/api/agents/{ws}/file", params={"path": "sibling"})
    assert r.status_code in (400, 404)


def test_git_status_and_versions(client, ws):
    save(client, ws, "keep.txt", "v1\n")
    save(client, ws, "gone.txt", "bye\n")
    assert run(ws, "git add -A && git commit -qm first").exit_code == 0
    save(client, ws, "keep.txt", "v2\n")
    save(client, ws, "new file.txt", "new\n")
    run(ws, "rm gone.txt")
    status = {e["path"]: e["worktree"] for e in data(client.get(f"/api/agents/{ws}/git/status"))}
    assert status == {"keep.txt": "M", "new file.txt": "?", "gone.txt": "D"}

    modified = data(client.get(f"/api/agents/{ws}/git/file", params={"path": "keep.txt"}))
    assert modified["head"]["content"] == "v1\n" and modified["working"]["content"] == "v2\n"
    new = data(client.get(f"/api/agents/{ws}/git/file", params={"path": "new file.txt"}))
    assert new["head"] is None and new["working"]["content"] == "new\n"
    gone = data(client.get(f"/api/agents/{ws}/git/file", params={"path": "gone.txt"}))
    assert gone["head"]["content"] == "bye\n" and gone["working"] is None


def test_versions_before_the_first_commit(client, ws):
    save(client, ws, "a.txt", "a")
    got = data(client.get(f"/api/agents/{ws}/git/file", params={"path": "a.txt"}))
    assert got["head"] is None and got["working"]["content"] == "a"
