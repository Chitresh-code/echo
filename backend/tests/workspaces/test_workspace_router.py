import base64

import pytest

WS = "0123456789abcdef" * 2


def done(exit_code=0):
    return {"exit_code": exit_code, "timed_out": False}


def out(data):
    return {"stream": "stdout", "data": data}


def test_create_and_list(client, fake_runner):
    created = client.post("/api/workspaces").json()
    assert created["success"] is True and len(created["data"]["id"]) == 32
    listed = client.get("/api/workspaces").json()
    assert listed["data"] == [{"id": created["data"]["id"]}] and listed["meta"]["request_id"]


@pytest.mark.parametrize("url", [
    "/api/workspaces/not-an-id/tree",
    f"/api/workspaces/{WS}/file?path=../etc/passwd",
    f"/api/workspaces/{WS}/file?path=/etc/passwd",
    f"/api/workspaces/{WS}/git/file?path=a/../../b",
])
def test_bad_id_or_path_is_400_before_the_runner(client, fake_runner, url):
    body = client.get(url).json()
    assert body["success"] is False and body["error"]["code"] in ("invalid_workspace_id", "invalid_path")
    assert fake_runner.requests == []


def test_save_with_bad_path_is_400_before_the_runner(client, fake_runner):
    r = client.put(f"/api/workspaces/{WS}/file", json={"path": "../x", "content": "hi"})
    assert r.status_code == 400 and fake_runner.requests == []


def test_tree_is_capped(client, fake_runner, monkeypatch):
    from apps.workspaces.services import workspace_service

    monkeypatch.setattr(workspace_service, "MAX_TREE_ENTRIES", 2)
    fake_runner.lines = [out("d src\0f src/a.py\0l link\0"), done()]
    data = client.get(f"/api/workspaces/{WS}/tree").json()["data"]
    assert data == {"entries": [{"path": "src", "type": "dir"}, {"path": "src/a.py", "type": "file"}], "truncated": True}
    assert fake_runner.requests[0]["workspace_id"] == WS


def test_read_text_file(client, fake_runner):
    fake_runner.queue = [[out("2\n"), done()], [out(base64.b64encode(b"12").decode()), done()]]
    data = client.get(f"/api/workspaces/{WS}/file?path=a.txt").json()["data"]
    assert data == {"path": "a.txt", "content": "12", "encoding": "utf-8"}
    assert f"/data/workspaces/{WS}/a.txt" in fake_runner.requests[1]["command"]


def test_binary_file_comes_back_as_base64(client, fake_runner):
    fake_runner.queue = [[out("2\n"), done()], [out(base64.b64encode(b"\xff\x00").decode()), done()]]
    data = client.get(f"/api/workspaces/{WS}/file?path=a.bin").json()["data"]
    assert data["encoding"] == "base64" and base64.b64decode(data["content"]) == b"\xff\x00"


def test_large_file_is_413(client, fake_runner):
    fake_runner.queue = [[out(f"{6 * 1024 * 1024}\n"), done()]]
    r = client.get(f"/api/workspaces/{WS}/file?path=big.bin")
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large" and len(fake_runner.requests) == 1


def test_missing_file_is_404(client, fake_runner):
    fake_runner.lines = [done(77)]
    r = client.get(f"/api/workspaces/{WS}/file?path=nope.txt")
    assert r.status_code == 404 and r.json()["error"]["code"] == "file_not_found"


def test_unknown_workspace_passes_the_runner_code_through(client, fake_runner):
    fake_runner.error = (404, {"success": False, "error": {"code": "workspace_not_found", "message": "There is no workspace with this id.", "details": None}})
    r = client.get(f"/api/workspaces/{WS}/git/status")
    assert r.status_code == 404 and r.json()["error"]["code"] == "workspace_not_found"


def test_failed_command_does_not_leak_stderr(client, fake_runner):
    fake_runner.lines = [{"stream": "stderr", "data": "secret file contents"}, done(128)]
    body = client.get(f"/api/workspaces/{WS}/git/status").json()
    assert body["error"]["code"] == "command_failed" and "secret" not in str(body)


def test_routes_are_documented(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    for path in ["/api/workspaces", "/api/workspaces/{workspace_id}/tree", "/api/workspaces/{workspace_id}/file", "/api/workspaces/{workspace_id}/git/status", "/api/workspaces/{workspace_id}/git/file"]:
        for operation in paths[path].values():
            assert operation["summary"] and "200" in operation["responses"]
