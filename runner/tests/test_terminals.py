import json
import os
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main, terminals


def _client(settings, monkeypatch):
    monkeypatch.setattr(os, "chown", lambda *a: None)
    return TestClient(main.create_app(settings))


@pytest.fixture
def client(fake_settings, monkeypatch):
    with _client(fake_settings, monkeypatch) as c:
        yield c


@pytest.fixture
def ws(client, ws_id):
    client.post(f"/workspaces/{ws_id}")
    return ws_id


def _open(client, ws, **size):
    r = client.post(f"/workspaces/{ws}/terminals", json=size)
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


def _read_until(sock, marker: bytes) -> bytes:
    seen = b""
    while marker not in seen:
        seen += sock.receive_bytes()
    return seen


def _type(sock, text: str):
    sock.send_text(json.dumps({"type": "input", "data": text}))


def _listed(client, ws):
    return [t["id"] for t in client.get(f"/workspaces/{ws}/terminals").json()["data"]["terminals"]]


def _wait(until, seconds=10):
    deadline = time.monotonic() + seconds
    while not until():
        assert time.monotonic() < deadline
        time.sleep(0.05)


def test_input_output_resize_and_replay(client, ws):
    tid = _open(client, ws, cols=100, rows=30)
    with client.websocket_connect(f"/workspaces/{ws}/terminals/{tid}") as sock:
        _type(sock, "echo he''llo\r")
        _read_until(sock, b"hello")
        sock.send_text(json.dumps({"type": "resize", "cols": 120, "rows": 40}))
        _type(sock, "stty size\r")
        _read_until(sock, b"40 120")
    # A second attach gets what was already shown, then carries on.
    with client.websocket_connect(f"/workspaces/{ws}/terminals/{tid}") as sock:
        replay = _read_until(sock, b"40 120")
        assert b"hello" in replay
        _type(sock, "echo ag''ain\r")
        _read_until(sock, b"again")
    assert _listed(client, ws) == [tid]


def test_exit_closes_the_socket_and_removes_the_terminal(client, ws):
    tid = _open(client, ws)
    with client.websocket_connect(f"/workspaces/{ws}/terminals/{tid}") as sock:
        _type(sock, "exit\r")
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                sock.receive_bytes()
        assert closed.value.code == 1000
    _wait(lambda: _listed(client, ws) == [])


def test_bad_frames_are_ignored_and_big_input_closes(client, ws):
    tid = _open(client, ws)
    with client.websocket_connect(f"/workspaces/{ws}/terminals/{tid}") as sock:
        sock.send_text("not json")
        sock.send_text(json.dumps({"type": "resize", "cols": "x"}))
        _type(sock, "echo st''ill\r")
        _read_until(sock, b"still")
        sock.send_text("x" * (main.TERMINAL_INPUT_MAX + 1))
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                sock.receive_bytes()
        assert closed.value.code == 1009
    # The shell itself is still there.
    assert _listed(client, ws) == [tid]


def test_delete_and_unknown(client, ws, ws_id, fake_settings):
    tid = _open(client, ws)
    assert client.delete(f"/workspaces/{ws}/terminals/{tid}").status_code == 200
    assert _listed(client, ws) == []
    assert client.delete(f"/workspaces/{ws}/terminals/{tid}").status_code == 404
    assert client.delete(f"/workspaces/{ws}/terminals/nope").status_code == 400
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(f"/workspaces/{ws}/terminals/{tid}") as sock:
            sock.receive_bytes()
    assert closed.value.code == 4404
    assert client.post(f"/workspaces/{'0' * 32}/terminals", json={}).status_code == 404
    assert client.post(f"/workspaces/{ws}/terminals", json={"cols": 0}).status_code == 422
    _wait(lambda: list((fake_settings.data_dir / "commands").iterdir()) == [])


def test_limits(client, ws, fake_settings):
    for _ in range(fake_settings.max_terminals_per_workspace):
        _open(client, ws)
    r = client.post(f"/workspaces/{ws}/terminals", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "too_many_terminals"


def test_workspace_delete_ends_terminals(client, ws):
    _open(client, ws)
    client.delete(f"/workspaces/{ws}")
    client.post(f"/workspaces/{ws}")
    assert _listed(client, ws) == []


def test_idle_terminal_is_ended(fake_settings, monkeypatch, ws_id):
    monkeypatch.setattr(terminals, "SWEEP_SECONDS", 0.05)
    with _client(replace(fake_settings, terminal_idle=0), monkeypatch) as client:
        client.post(f"/workspaces/{ws_id}")
        attached = _open(client, ws_id)
        with client.websocket_connect(f"/workspaces/{ws_id}/terminals/{attached}") as sock:
            _open(client, ws_id)
            _wait(lambda: _listed(client, ws_id) == [attached])
            # The attached one is still alive.
            _type(sock, "echo al''ive\r")
            _read_until(sock, b"alive")
