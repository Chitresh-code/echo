"""New files and folders from the explorer, and uploads from the user's machine."""

import pytest

from tests.helpers.accounts import own, sign_in_as

WS = "0123456789abcdef" * 2
FILES = f"/api/agents/{WS}/files"


@pytest.fixture(autouse=True)
def _owns_ws(client, user):
    own(client, user, WS)


def done(exit_code=0):
    return {"exit_code": exit_code, "timed_out": False}


def out(data):
    return {"stream": "stdout", "data": data}


def code(r):
    return r.json()["error"]["code"]


def test_create_refuses_a_taken_path(client, fake_runner):
    fake_runner.lines = [done(79)]
    r = client.put(f"/api/agents/{WS}/file", json={"path": "src/a.ts", "content": "", "create": True})
    assert r.status_code == 409 and code(r) == "path_exists"
    assert "set -C" in fake_runner.requests[0]["command"] and len(fake_runner.requests) == 1


def test_create_makes_an_empty_file_in_one_command(client, fake_runner):
    fake_runner.lines = [done()]
    r = client.put(f"/api/agents/{WS}/file", json={"path": "src/lib/a.ts", "content": "", "create": True})
    assert r.status_code == 200 and len(fake_runner.requests) == 1
    assert f"/data/workspaces/{WS}/src/lib/a.ts" in fake_runner.requests[0]["command"]


def test_folder_is_made_with_parents_and_refused_if_taken(client, fake_runner):
    fake_runner.lines = [done()]
    assert client.post(f"/api/agents/{WS}/folders", json={"path": "a/b/c"}).json()["data"] == {"path": "a/b/c"}
    assert "mkdir -p" in fake_runner.requests[0]["command"]
    fake_runner.lines = [done(79)]
    assert code(client.post(f"/api/agents/{WS}/folders", json={"path": "a"})) == "path_exists"


@pytest.mark.parametrize("path", ["../x", "/etc", "", "a/../../b"])
def test_bad_folder_paths_never_reach_the_runner(client, fake_runner, path):
    assert client.post(f"/api/agents/{WS}/folders", json={"path": path}).status_code == 400 and fake_runner.requests == []


def test_another_users_agent_is_not_found(client, fake_runner):
    sign_in_as(client, "other-user")
    assert client.post(f"/api/agents/{WS}/folders", json={"path": "a"}).status_code == 404
    assert client.post(FILES, files={"files": ("a.txt", b"hi")}).status_code == 404
    assert fake_runner.requests == []


def test_upload_text_and_binary_into_a_folder(client, fake_runner):
    # The existence check, then one write per file.
    fake_runner.queue = [[done()], [done()], [done()]]
    r = client.post(FILES, data={"folder": "assets"}, files=[("files", ("a.txt", b"hi")), ("files", ("logo.png", b"\x89PNG\x00\xff"))])
    assert r.json()["data"] == {"written": ["assets/a.txt", "assets/logo.png"]}
    assert len(fake_runner.requests) == 3 and f"{WS}/assets/logo.png" in fake_runner.requests[2]["command"]


def test_taken_names_are_listed_and_nothing_is_written(client, fake_runner):
    fake_runner.lines = [out("a.txt\0"), done()]
    r = client.post(FILES, files=[("files", ("a.txt", b"hi")), ("files", ("b.txt", b"yo"))])
    assert r.status_code == 409 and code(r) == "files_exist" and r.json()["error"]["details"] == {"paths": ["a.txt"]}
    assert len(fake_runner.requests) == 1


def test_overwrite_skips_the_check(client, fake_runner):
    fake_runner.lines = [done()]
    r = client.post(FILES, data={"overwrite": "true"}, files={"files": ("a.txt", b"hi")})
    assert r.json()["data"] == {"written": ["a.txt"]} and len(fake_runner.requests) == 1


@pytest.mark.parametrize("name, landed", [("../../etc/passwd", "passwd"), ("C:\\Users\\me\\x.csv", "x.csv"), ("dir/a.txt", "a.txt")])
def test_only_the_file_name_is_kept(client, fake_runner, name, landed):
    fake_runner.lines = [done()]
    r = client.post(FILES, data={"overwrite": "true"}, files={"files": (name, b"x")})
    assert r.json()["data"] == {"written": [landed]}


@pytest.mark.parametrize("name", ["..", "."])
def test_names_that_are_not_files_are_refused(client, fake_runner, name):
    r = client.post(FILES, files={"files": (name, b"x")})
    assert r.status_code == 400 and fake_runner.requests == []


def test_limits(client, fake_runner):
    many = [("files", (f"{i}.txt", b"x")) for i in range(21)]
    assert code(client.post(FILES, files=many)) == "too_many_files"
    assert code(client.post(FILES, files={"files": ("big.bin", b"x" * (5 * 1024 * 1024 + 1))})) == "file_too_large"
    six = [("files", (f"{i}.bin", b"x" * (5 * 1024 * 1024))) for i in range(6)]
    assert code(client.post(FILES, files=six)) == "upload_too_large"
    assert code(client.post(FILES, data={"folder": "a"})) == "no_files"
    assert code(client.post(FILES, files=[("files", ("a.txt", b"1")), ("files", ("x/a.txt", b"2"))])) == "duplicate_names"
    assert fake_runner.requests == []


def test_full_workspace_refuses_uploads(client, fake_runner):
    fake_runner.usage = {"used_bytes": 3000, "limit_bytes": 2000}
    r = client.post(FILES, files={"files": ("a.txt", b"hi")})
    assert r.status_code == 507 and fake_runner.requests == []
