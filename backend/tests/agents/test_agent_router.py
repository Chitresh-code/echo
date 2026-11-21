import base64

import pytest

from tests.helpers.accounts import own

WS = "0123456789abcdef" * 2


@pytest.fixture(autouse=True)
def _owns_ws(client, user):
    own(client, user, WS)


def done(exit_code=0):
    return {"exit_code": exit_code, "timed_out": False}


def out(data):
    return {"stream": "stdout", "data": data}


def test_create_and_list_newest_first(client, fake_runner):
    created = client.post("/api/agents", json={"name": "  Payout reconciliation ", "job": "Match payouts to the ledger"}).json()
    assert created["success"] is True and len(created["data"]["id"]) == 32
    assert created["data"]["name"] == "Payout reconciliation" and created["data"]["job"] == "Match payouts to the ledger"
    assert created["data"]["last_used_at"] is None
    assert fake_runner.workspaces == [created["data"]["id"]]
    listed = client.get("/api/agents").json()
    assert [a["id"] for a in listed["data"]] == [created["data"]["id"], WS] and listed["meta"]["request_id"]
    assert listed["data"][1]["name"] == "Untitled agent" and listed["data"][1]["job"] == ""


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "   "}, {"name": "x" * 81}, {"name": "ok", "job": "x" * 501}])
def test_create_checks_name_and_job(client, fake_runner, body):
    r = client.post("/api/agents", json=body)
    assert r.status_code == 422 and fake_runner.requests == [] and fake_runner.workspaces == []


def test_patch_renames_and_changes_the_job(client):
    r = client.patch(f"/api/agents/{WS}", json={"name": "Release notes"})
    assert r.json()["data"]["name"] == "Release notes" and r.json()["data"]["job"] == ""
    r = client.patch(f"/api/agents/{WS}", json={"job": "Draft release notes from merged PRs"})
    assert r.json()["data"]["name"] == "Release notes" and r.json()["data"]["job"] == "Draft release notes from merged PRs"
    assert client.patch(f"/api/agents/{WS}", json={"name": ""}).status_code == 422


def test_get_one_agent(client):
    assert client.get(f"/api/agents/{WS}").json()["data"]["name"] == "Untitled agent"


def test_patch_on_a_missing_agent_is_404(client):
    r = client.patch(f"/api/agents/{'d' * 32}", json={"name": "x"})
    assert (r.status_code, r.json()["error"]["code"]) == (404, "agent_not_found")


def test_list_puts_the_most_recently_used_first(client, fake_runner):
    newer = client.post("/api/agents", json={"name": "Newer"}).json()["data"]["id"]
    assert [a["id"] for a in client.get("/api/agents").json()["data"]] == [newer, WS]
    _touch(client, WS)
    listed = client.get("/api/agents").json()["data"]
    assert [a["id"] for a in listed] == [WS, newer] and listed[0]["last_used_at"]


@pytest.mark.parametrize("url", [
    "/api/agents/not-an-id/tree",
    f"/api/agents/{WS}/file?path=../etc/passwd",
    f"/api/agents/{WS}/file?path=/etc/passwd",
    f"/api/agents/{WS}/git/file?path=a/../../b",
])
def test_bad_id_or_path_is_400_before_the_runner(client, fake_runner, url):
    body = client.get(url).json()
    assert body["success"] is False and body["error"]["code"] in ("invalid_agent_id", "invalid_path")
    assert fake_runner.requests == []


def test_save_with_bad_path_is_400_before_the_runner(client, fake_runner):
    r = client.put(f"/api/agents/{WS}/file", json={"path": "../x", "content": "hi"})
    assert r.status_code == 400 and fake_runner.requests == []


def test_tree_is_capped(client, fake_runner, monkeypatch):
    from apps.agents.services import agent_service

    monkeypatch.setattr(agent_service, "MAX_TREE_ENTRIES", 2)
    fake_runner.lines = [out("d src\0f src/a.py\0l link\0"), done()]
    data = client.get(f"/api/agents/{WS}/tree").json()["data"]
    assert data == {"entries": [{"path": "src", "type": "dir"}, {"path": "src/a.py", "type": "file"}], "truncated": True}
    assert fake_runner.requests[0]["workspace_id"] == WS


def test_read_text_file(client, fake_runner):
    fake_runner.queue = [[out("2\n"), done()], [out(base64.b64encode(b"12").decode()), done()]]
    data = client.get(f"/api/agents/{WS}/file?path=a.txt").json()["data"]
    assert data == {"path": "a.txt", "content": "12", "encoding": "utf-8"}
    assert f"/data/workspaces/{WS}/a.txt" in fake_runner.requests[1]["command"]


def test_binary_file_comes_back_as_base64(client, fake_runner):
    fake_runner.queue = [[out("2\n"), done()], [out(base64.b64encode(b"\xff\x00").decode()), done()]]
    data = client.get(f"/api/agents/{WS}/file?path=a.bin").json()["data"]
    assert data["encoding"] == "base64" and base64.b64decode(data["content"]) == b"\xff\x00"


def test_large_file_is_413(client, fake_runner):
    fake_runner.queue = [[out(f"{6 * 1024 * 1024}\n"), done()]]
    r = client.get(f"/api/agents/{WS}/file?path=big.bin")
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large" and len(fake_runner.requests) == 1


def test_missing_file_is_404(client, fake_runner):
    fake_runner.lines = [done(77)]
    r = client.get(f"/api/agents/{WS}/file?path=nope.txt")
    assert r.status_code == 404 and r.json()["error"]["code"] == "file_not_found"


def test_unknown_workspace_passes_the_runner_code_through(client, fake_runner):
    fake_runner.error = (404, {"success": False, "error": {"code": "workspace_not_found", "message": "There is no workspace with this id.", "details": None}})
    r = client.get(f"/api/agents/{WS}/git/status")
    assert r.status_code == 404 and r.json()["error"]["code"] == "workspace_not_found"


def test_failed_command_does_not_leak_stderr(client, fake_runner):
    fake_runner.lines = [{"stream": "stderr", "data": "secret file contents"}, done(128)]
    body = client.get(f"/api/agents/{WS}/git/status").json()
    assert body["error"]["code"] == "command_failed" and "secret" not in str(body)


def test_routes_are_documented(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    for path in ["/api/agents", "/api/agents/{agent_id}", "/api/agents/{agent_id}/tree", "/api/agents/{agent_id}/file", "/api/agents/{agent_id}/git/status", "/api/agents/{agent_id}/git/file"]:
        for operation in paths[path].values():
            assert operation["summary"] and "200" in operation["responses"]


def _touch(client, agent_id):
    from sqlalchemy.ext.asyncio import AsyncSession

    from apps.agents.repositories import agents

    async def go():
        async with AsyncSession(client.app.state.db_engine) as db:
            await agents.touch(db, agent_id)
            await db.commit()

    client.portal.call(go)
