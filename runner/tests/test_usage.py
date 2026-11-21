import dataclasses
import json
import os

import pytest
from fastapi.testclient import TestClient

from app import jail, main, usage


@pytest.fixture
def client(fake_settings, monkeypatch):
    monkeypatch.setattr(os, "chown", lambda *a: None)
    return TestClient(main.create_app(fake_settings))


def test_walk_counts_workspace_and_home_once_and_stays_inside(tmp_path):
    ws, home, outside = tmp_path / "ws", tmp_path / "home", tmp_path / "outside"
    for d in (ws, home, outside):
        d.mkdir()
    (ws / "a").write_bytes(b"x" * 100_000)
    (home / "b").write_bytes(b"y" * 100_000)
    os.link(ws / "a", ws / "a-again")
    (outside / "big").write_bytes(b"z" * 1_000_000)
    os.symlink(outside, ws / "link")
    used = usage._walk([ws, home])
    # Two 100 KB files (block rounding aside), not the hard link twice and not what the link points at.
    assert 200_000 <= used < 400_000


def test_usage_endpoint_and_unknown_workspace(client, fake_settings, ws_id):
    assert client.get(f"/workspaces/{ws_id}/usage").json()["error"]["code"] == "workspace_not_found"
    client.post(f"/workspaces/{ws_id}")
    (fake_settings.data_dir / "workspaces" / ws_id / "f").write_bytes(b"x" * 50_000)
    usage.forget(ws_id)
    data = client.get(f"/workspaces/{ws_id}/usage").json()["data"]
    assert data["used_bytes"] >= 50_000 and data["limit_bytes"] == fake_settings.disk_mb * 1024 * 1024


def test_full_workspace_runs_commands_with_a_warning(fake_settings, ws_id, monkeypatch):
    monkeypatch.setattr(os, "chown", lambda *a: None)
    tiny = dataclasses.replace(fake_settings, disk_mb=0)
    client = TestClient(main.create_app(tiny))
    client.post(f"/workspaces/{ws_id}")
    usage.forget(ws_id)
    seen = {}
    real = jail.build_argv
    monkeypatch.setattr(jail, "build_argv", lambda *a, **k: seen.update(k) or real(*a, **k))
    r = client.post(f"/workspaces/{ws_id}/exec", json={"command": "echo still runs"})
    lines = [json.loads(line) for line in r.text.splitlines()]
    assert lines[0]["stream"] == "stderr" and "limit, so files cannot be written" in lines[0]["data"]
    assert {"stream": "stdout", "data": "still runs\n"} in lines and seen["fsize_mb"] == 0


def test_delete_removes_both_folders_but_not_a_link_target(client, fake_settings, ws_id, tmp_path):
    client.post(f"/workspaces/{ws_id}")
    target = tmp_path / "keep"
    target.mkdir()
    (target / "file").write_text("safe")
    os.symlink(target, fake_settings.data_dir / "workspaces" / ws_id / "link")
    assert client.delete(f"/workspaces/{ws_id}").json() == {"success": True, "data": {"deleted": True}}
    assert not (fake_settings.data_dir / "workspaces" / ws_id).exists() and not (fake_settings.data_dir / "homes" / ws_id).exists()
    assert (target / "file").read_text() == "safe"
    assert client.delete(f"/workspaces/{ws_id}").json()["error"]["code"] == "workspace_not_found"
    assert client.delete("/workspaces/not-an-id").json()["error"]["code"] == "invalid_workspace_id"
