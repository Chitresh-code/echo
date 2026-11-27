import pytest
from starlette.websockets import WebSocketDisconnect

from apps.accounts.services.session_service import COOKIE
from tests.helpers.accounts import sign_in_as

ORIGIN = {"origin": "http://testserver"}


@pytest.fixture
def agent(client, user):
    return client.post("/api/agents", json={"name": "Test agent"}).json()["data"]["id"]


def _url(agent, tid):
    return f"/api/agents/{agent}/terminals/{tid}"


def _closed_with(client, url, headers=ORIGIN) -> int:
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(url, headers=headers) as sock:
            sock.receive_bytes()
    return closed.value.code


def test_open_list_close(client, agent, fake_runner):
    r = client.post(f"/api/agents/{agent}/terminals", json={"cols": 100, "rows": 30})
    assert r.status_code == 200
    tid = r.json()["data"]["id"]
    assert fake_runner.requests[-1] == {"workspace_id": agent, "terminal": {"cols": 100, "rows": 30}}
    assert [t["id"] for t in client.get(f"/api/agents/{agent}/terminals").json()["data"]["terminals"]] == [tid]
    assert client.delete(_url(agent, tid)).json()["data"] == {"deleted": True}
    r = client.delete(_url(agent, tid))
    assert (r.status_code, r.json()["error"]["code"]) == (404, "terminal_not_found")
    assert client.delete(_url(agent, "../x")).status_code == 404
    assert client.post(f"/api/agents/{agent}/terminals", json={"cols": 0}).status_code == 422


def test_frames_pass_both_ways_and_the_runner_close_is_passed_on(client, agent, fake_runner):
    tid = client.post(f"/api/agents/{agent}/terminals", json={}).json()["data"]["id"]
    with client.websocket_connect(_url(agent, tid), headers=ORIGIN) as sock:
        assert sock.receive_bytes() == b"replay"
        sock.send_text('{"type":"input","data":"ls\\r"}')
        assert sock.receive_bytes() == b'got:{"type":"input","data":"ls\\r"}'
        sock.send_bytes(b"ignored")
        sock.send_text("exit")
        with pytest.raises(WebSocketDisconnect) as closed:
            sock.receive_bytes()
        assert closed.value.code == 1000
    assert fake_runner.terminal_frames == ['{"type":"input","data":"ls\\r"}', "exit"]


def test_socket_refusals(client, agent, fake_runner):
    tid = client.post(f"/api/agents/{agent}/terminals", json={}).json()["data"]["id"]
    # Another site's page: refused at the handshake.
    assert _closed_with(client, _url(agent, tid), {"origin": "https://evil.example"}) == 4403
    # A terminal that is not there, or an id that is not one.
    assert _closed_with(client, _url(agent, "f" * 32)) == 4404
    assert _closed_with(client, _url(agent, "nope")) == 4404
    # Someone else's agent looks the same as a missing one.
    ada = client.cookies[COOKIE]
    sign_in_as(client, "bob")
    assert _closed_with(client, _url(agent, tid)) == 4404
    client.cookies.delete(COOKIE)
    assert _closed_with(client, _url(agent, tid)) == 4401
    client.cookies.set(COOKIE, ada)
    assert fake_runner.terminal_frames == []


def test_runner_down(client, agent, fake_runner, monkeypatch, tmp_path):
    tid = client.post(f"/api/agents/{agent}/terminals", json={}).json()["data"]["id"]
    monkeypatch.setenv("ECHO_RUNNER_SOCKET", str(tmp_path / "none.sock"))
    from core.config import get_settings

    get_settings.cache_clear()
    assert _closed_with(client, _url(agent, tid)) == 1011
