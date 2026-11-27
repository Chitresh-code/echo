import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main, preview


@pytest.fixture
def client(fake_settings, monkeypatch):
    monkeypatch.setattr(os, "chown", lambda *a: None)
    with TestClient(main.create_app(fake_settings)) as c:
        yield c


def test_client_connects_only_through_the_namespace_backend():
    # Pins the private httpx attribute the backend is set on; an upgrade that moves it fails here.
    c = preview.client(Path("/run/netns/x"), 3000)
    assert isinstance(c._transport._pool._network_backend, preview._NamespaceBackend)
    assert c._trust_env is False and c.follow_redirects is False


def test_hop_by_hop_headers_are_dropped_and_repeats_kept():
    raw = [(b"Host", b"localhost:3000"), (b"Connection", b"keep-alive, X-Secret"), (b"X-Secret", b"1"), (b"Transfer-Encoding", b"chunked"),
           (b"Upgrade", b"websocket"), (b"Set-Cookie", b"a=1"), (b"Set-Cookie", b"b=2")]
    assert preview.end_to_end(raw) == [(b"Host", b"localhost:3000"), (b"Set-Cookie", b"a=1"), (b"Set-Cookie", b"b=2")]


@pytest.mark.parametrize("raw, query, target", [
    (b"/workspaces/ab/ports/3000/http/", b"", b"/"),
    (b"/workspaces/ab/ports/3000/http/a/b%2Fc", b"x=1&y=%20", b"/a/b%2Fc?x=1&y=%20"),
    (b"/workspaces/ab/ports/3000/http/@vite/client", b"", b"/@vite/client"),
])
def test_upstream_target_keeps_the_path_as_sent(raw, query, target):
    assert preview.upstream_target(raw, query) == target


def test_refused_before_connecting(client, ws_id):
    assert client.get(f"/workspaces/{ws_id}/ports/3000/http/").json()["error"]["code"] == "workspace_not_found"
    client.post(f"/workspaces/{ws_id}")
    # The fake ip makes no namespace, as when nothing has run since a restart.
    r = client.get(f"/workspaces/{ws_id}/ports/3000/http/")
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_network"
    for port in (0, 65536, "x"):
        assert client.get(f"/workspaces/{ws_id}/ports/{port}/http/").status_code == 422
    assert client.get("/workspaces/not-an-id/ports/3000/http/").status_code == 400
