import json
import os
import stat
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def client(fake_settings, monkeypatch):
    # chown needs root; the ownership itself is checked by the jail tests.
    monkeypatch.setattr(os, "chown", lambda *a: None)
    return TestClient(main.create_app(fake_settings))


def _lines(r):
    return [json.loads(line) for line in r.text.splitlines()]


def test_create_and_list(client, fake_settings, ws_id):
    r = client.post(f"/workspaces/{ws_id}")
    assert r.json() == {"success": True, "data": {"id": ws_id}}
    assert (fake_settings.data_dir / "workspaces" / ws_id / ".agent" / "skills").is_dir()
    assert (fake_settings.data_dir / "homes" / ws_id).is_dir()
    assert client.post(f"/workspaces/{ws_id}").status_code == 200  # idempotent
    assert client.get("/workspaces").json()["data"] == [ws_id]


def test_exec_streams_and_exits(client, ws_id):
    client.post(f"/workspaces/{ws_id}")
    r = client.post(f"/workspaces/{ws_id}/exec", json={"command": "echo out; echo err >&2; exit 3"})
    lines = _lines(r)
    assert {"stream": "stdout", "data": "out\n"} in lines and {"stream": "stderr", "data": "err\n"} in lines
    assert lines[-1] == {"exit_code": 3, "timed_out": False}


def test_long_command_runs_and_its_file_is_removed(client, fake_settings, ws_id):
    # Past Linux's 128 KB limit for one argument, like a file write carrying base64 content.
    client.post(f"/workspaces/{ws_id}")
    payload = "a" * 300_000
    r = client.post(f"/workspaces/{ws_id}/exec", json={"command": f"echo {payload} | wc -c"})
    assert _lines(r)[0]["data"].strip() == "300001"
    assert list((fake_settings.data_dir / "commands").iterdir()) == []


def test_exec_unknown_workspace(client, ws_id):
    r = client.post(f"/workspaces/{ws_id}/exec", json={"command": "true"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "workspace_not_found"


def test_exec_bad_id_and_cwd_are_400(client, ws_id):
    assert client.post("/workspaces/not-an-id/exec", json={"command": "true"}).json()["error"]["code"] == "invalid_workspace_id"
    client.post(f"/workspaces/{ws_id}")
    r = client.post(f"/workspaces/{ws_id}/exec", json={"command": "true", "cwd": "/etc"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cwd"


def test_backstop_kills_a_hung_jail(client, ws_id, monkeypatch):
    # The fake nsjail has no time limit of its own, so this exercises the runner's backstop.
    monkeypatch.setattr(main.jail, "BACKSTOP_SECONDS", 0)
    client.post(f"/workspaces/{ws_id}")
    r = client.post(f"/workspaces/{ws_id}/exec", json={"command": "echo before; sleep 30", "timeout": 1})
    lines = _lines(r)
    assert lines[0] == {"stream": "stdout", "data": "before\n"}
    assert lines[-1]["timed_out"] is True


def test_socket_only_owner_can_connect(monkeypatch):
    monkeypatch.setattr(os, "chown", lambda *a: None)
    # Unix socket paths are limited to about 100 bytes, and pytest's tmp_path can be longer.
    path = Path(tempfile.mkdtemp(dir="/tmp")) / "runner.sock"
    sock = main.bind_socket(path, 10001)
    try:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        sock.close()
