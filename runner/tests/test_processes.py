import os
import time

import pytest
from fastapi.testclient import TestClient

from app import main, processes


@pytest.fixture
def client(fake_settings, monkeypatch):
    monkeypatch.setattr(os, "chown", lambda *a: None)
    with TestClient(main.create_app(fake_settings)) as c:
        yield c


@pytest.fixture
def ws(client, ws_id):
    client.post(f"/workspaces/{ws_id}")
    return ws_id


def _wait(client, ws, until, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        data = client.get(f"/workspaces/{ws}/processes").json()["data"]
        if until(data):
            return data
        time.sleep(0.05)
    raise AssertionError(data)


def _start(client, ws, name, command):
    return client.post(f"/workspaces/{ws}/processes", json={"name": name, "command": command})


def test_start_logs_stop(client, ws):
    r = _start(client, ws, "web", "echo hello; echo oops >&2; sleep 30")
    assert r.status_code == 200 and r.json()["data"]["status"] == "running"
    _wait(client, ws, lambda d: d["processes"][0]["status"] == "running")
    deadline = time.monotonic() + 5
    while "oops" not in (log := client.get(f"/workspaces/{ws}/processes/web/logs").json()["data"]["log"]):
        assert time.monotonic() < deadline
        time.sleep(0.05)
    assert "hello" in log
    r = client.delete(f"/workspaces/{ws}/processes/web")
    assert r.json()["data"]["status"] == "exited"


def test_exited_process_is_listed_and_can_be_replaced(client, ws, fake_settings):
    _start(client, ws, "job", "exit 4")
    data = _wait(client, ws, lambda d: d["processes"][0]["status"] == "exited")
    assert data["processes"][0]["exit_code"] == 4
    assert _start(client, ws, "job", "sleep 30").status_code == 200
    assert _start(client, ws, "job", "sleep 30").json()["error"]["code"] == "process_exists"
    # The command file stays while the process runs and goes when it exits.
    assert len(list((fake_settings.data_dir / "commands").iterdir())) == 1


def test_limits(client, ws, fake_settings):
    for n in range(fake_settings.max_processes_per_workspace):
        assert _start(client, ws, f"p{n}", "sleep 30").status_code == 200
    r = _start(client, ws, "one-more", "sleep 30")
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_processes"


def test_host_limit(fake_settings, monkeypatch):
    from dataclasses import replace
    import uuid

    monkeypatch.setattr(os, "chown", lambda *a: None)
    with TestClient(main.create_app(replace(fake_settings, max_processes=1))) as client:
        a, b = uuid.uuid4().hex, uuid.uuid4().hex
        client.post(f"/workspaces/{a}"), client.post(f"/workspaces/{b}")
        assert _start(client, a, "x", "sleep 30").status_code == 200
        assert _start(client, b, "x", "sleep 30").status_code == 429


def test_bad_names_and_unknowns(client, ws, ws_id):
    for name in ("", "Web", "-web", "a" * 33, "../x", "a b"):
        assert _start(client, ws, name, "true").json()["error"]["code"] == "invalid_process_name", name
    assert client.get(f"/workspaces/{ws}/processes/nope/logs").status_code == 404
    assert client.delete(f"/workspaces/{ws}/processes/nope").status_code == 404
    other = "0" * 32
    assert client.get(f"/workspaces/{other}/processes").json()["error"]["code"] == "workspace_not_found"


def test_workspace_delete_stops_processes_and_removes_logs(client, ws, fake_settings):
    _start(client, ws, "web", "echo hi; sleep 30")
    assert client.delete(f"/workspaces/{ws}").status_code == 200
    assert not processes.logs_dir(fake_settings, ws).exists()
    assert list((fake_settings.data_dir / "commands").iterdir()) == []


def test_log_is_cut_back_at_its_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(processes, "LOG_MAX", 100)
    monkeypatch.setattr(processes, "LOG_KEEP", 40)
    log = tmp_path / "x.log"
    for n in range(50):
        processes.append_log(log, f"line {n}\n".encode())
    text = log.read_text()
    assert len(text) <= 100 and text.startswith("line ") and text.endswith("line 49\n")
    assert oct(log.stat().st_mode & 0o777) == "0o600"


def test_tail(tmp_path):
    log = tmp_path / "x.log"
    log.write_text("".join(f"{n}\n" for n in range(2000)))
    assert processes.tail(log, 3) == "1997\n1998\n1999"
    assert len(processes.tail(log, 5000).splitlines()) == processes.TAIL_LINES_MAX
    assert processes.tail(tmp_path / "missing", 3) == ""


def test_parse_listening():
    tcp = (
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 1\n"
        "   1: 0100007F:1F90 0100007F:D3C2 01 00000000:00000000 00:00000000 00000000  1000        0 2\n"
    )
    tcp6 = (
        "  sl  local_address                         remote_address                        st\n"
        "   0: 00000000000000000000000000000000:1435 00000000000000000000000000000000:0000 0A\n"
    )
    assert processes.parse_listening(tcp) | processes.parse_listening(tcp6) == {8080, 5173}
