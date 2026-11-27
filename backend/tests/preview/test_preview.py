"""Previews: the setting, host dispatch, the start token and cookie, and what is passed to and from
the agent's server."""

import pytest
from fastapi.testclient import TestClient

from apps.preview.services import preview_service
from core.config import ConfigError, load_settings
from core.preview_host import preview_target
from tests.conftest import TEST_ENV
from tests.helpers.accounts import sign_in_as

PREVIEW = "http://preview.localhost:8000"


# The setting


@pytest.mark.parametrize("value", [
    "http://testserver", "http://a.testserver", "ftp://preview.localhost", "http://preview.localhost/path",
    "http://preview.example.com", "preview.localhost",
])
def test_bad_preview_urls_are_refused(value):
    with pytest.raises(ConfigError, match="ECHO_PREVIEW_URL"):
        load_settings({**TEST_ENV, "ECHO_PREVIEW_URL": value})


def test_a_preview_domain_above_echos_is_refused():
    with pytest.raises(ConfigError, match="ECHO_PREVIEW_URL"):
        load_settings({**TEST_ENV, "ECHO_PUBLIC_URL": "https://echo.example.com", "ECHO_PREVIEW_URL": "https://example.com"})


def test_good_preview_urls():
    assert load_settings(TEST_ENV).preview_url is None
    local = {**TEST_ENV, "ECHO_PUBLIC_URL": "http://localhost:8000", "ECHO_PREVIEW_URL": PREVIEW}
    assert load_settings(local).preview_url == PREVIEW
    with pytest.raises(ConfigError):
        load_settings({**local, "ECHO_PREVIEW_URL": "http://localhost:9000"})
    assert load_settings({**TEST_ENV, "ECHO_PREVIEW_URL": "http://Preview.localhost:8000/"}).preview_url == PREVIEW
    assert load_settings({**TEST_ENV, "ECHO_PREVIEW_URL": "https://echo-preview.example.net"}).preview_url == "https://echo-preview.example.net"


def test_preview_target():
    a = "a" * 32
    assert preview_target(f"{a}-3000.preview.localhost:8000", PREVIEW) == (a, 3000)
    assert preview_target(f"{a.upper()}-3000.preview.localhost", PREVIEW) == (a, 3000)
    for host in ("preview.localhost:8000", f"x.{a}-3000.preview.localhost", f"{a}-0.preview.localhost", f"{a}-70000.preview.localhost", "abc-3000.preview.localhost"):
        assert preview_target(host, PREVIEW) is False, host
    for host in ("localhost:8000", "testserver", f"{a}-3000.preview.localhost.evil.com", "evilpreview.localhost"):
        assert preview_target(host, PREVIEW) is None, host


# Serving


@pytest.fixture
def on(monkeypatch, settings_env):
    monkeypatch.setenv("ECHO_PREVIEW_URL", PREVIEW)
    from core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
def agent(on, client, fake_runner):
    """A signed-in user's agent id, and that user's id."""
    user_id = sign_in_as(client)
    return client.post("/api/agents", json={"name": "Site"}).json()["data"]["id"], user_id


def host(agent_id, port=3000):
    return f"{agent_id}-{port}.preview.localhost:8000"


def start(client, agent_id, port=3000):
    url = client.post(f"/api/agents/{agent_id}/preview", json={"port": port}).json()["data"]["url"]
    assert url.startswith(f"http://{host(agent_id, port)}/.echo-preview/start?token=")
    return url.split("token=")[1]


def cookie_from(client, agent_id, token, port=3000):
    r = client.get("/.echo-preview/start", params={"token": token}, headers={"host": host(agent_id, port)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/", r.text
    return r.headers["set-cookie"]


def test_start_sets_a_cookie_for_this_host_only(agent, client):
    agent_id, _ = agent
    set_cookie = cookie_from(client, agent_id, start(client, agent_id))
    assert set_cookie.startswith("echo_preview=")
    for flag in ("HttpOnly", "Secure", "SameSite=None", "Partitioned", "Path=/", "Max-Age=28800"):
        assert flag in set_cookie
    assert "Domain" not in set_cookie


def test_a_page_is_forwarded_with_its_cookie_stripped(agent, client, fake_runner):
    agent_id, _ = agent
    value = cookie_from(client, agent_id, start(client, agent_id)).split(";")[0]
    fake_runner.preview_answer = (200, [("content-type", "text/html"), ("set-cookie", "echo_preview=forged; Path=/"), ("set-cookie", "sid=1"), ("set-cookie", "theme=dark; Domain=.preview.localhost")], b"<p>hi</p>")
    r = client.get("/a%2Fb/page?x=1", headers={"host": host(agent_id), "cookie": f"sid=1; {value}; theme=dark"})
    assert r.status_code == 200 and r.text == "<p>hi</p>"
    call = fake_runner.previews[-1]
    assert (call["workspace_id"], call["port"], call["raw_path"], call["query"]) == (agent_id, 3000, f"/workspaces/{agent_id}/ports/3000/http/a%2Fb/page".encode(), b"x=1")
    sent = dict(call["headers"])
    assert sent[b"host"] == b"localhost:3000"
    assert sent[b"cookie"] == b"sid=1; theme=dark"
    assert r.headers.get_list("set-cookie") == ["sid=1", "theme=dark"]
    assert r.headers["content-security-policy"] == "frame-ancestors http://testserver"


def test_a_post_body_reaches_the_server(agent, client, fake_runner):
    agent_id, _ = agent
    value = cookie_from(client, agent_id, start(client, agent_id)).split(";")[0]
    # From the preview's own origin, which the api's origin check would refuse: this never reaches it.
    r = client.post("/form", content=b"a=1", headers={"host": host(agent_id), "cookie": value, "origin": f"http://{host(agent_id)}"})
    assert r.status_code == 200 and fake_runner.previews[-1]["body"] == b"a=1"
    r = client.post("/big", headers={"host": host(agent_id), "cookie": value, "content-length": str(11 * 1024 * 1024)}, content=b"")
    assert r.status_code == 413


def test_no_cookie_or_a_bad_one_is_refused(agent, client, fake_runner):
    agent_id, _ = agent
    for cookie in (None, "echo_preview=nope"):
        r = client.get("/", headers={"host": host(agent_id), **({"cookie": cookie} if cookie else {})})
        assert r.status_code == 403 and "Open this preview from Echo" in r.text
    assert fake_runner.previews == []


def test_a_token_or_cookie_only_works_on_its_own_host(agent, client, fake_runner):
    agent_id, _ = agent
    token = start(client, agent_id, 3000)
    r = client.get("/.echo-preview/start", params={"token": token}, headers={"host": host(agent_id, 3001)})
    assert r.status_code == 403
    value = cookie_from(client, agent_id, token).split(";")[0]
    assert client.get("/", headers={"host": host(agent_id, 3001), "cookie": value}).status_code == 403
    # A start token is not a cookie.
    assert client.get("/", headers={"host": host(agent_id), "cookie": f"echo_preview={token}"}).status_code == 403
    assert fake_runner.previews == []


def test_an_old_token_is_refused(agent, client, monkeypatch):
    agent_id, _ = agent
    token = start(client, agent_id)
    monkeypatch.setattr(preview_service, "TOKEN_SECONDS", -1)
    assert client.get("/.echo-preview/start", params={"token": token}, headers={"host": host(agent_id)}).status_code == 403


def test_another_users_or_a_deleted_agent_is_refused(agent, client, fake_runner):
    agent_id, user_id = agent
    from core.config import get_settings

    # Signed by Echo for another user, as if Echo had been asked to by them.
    stranger = preview_service.cookie_value(get_settings(), "someone-else", agent_id, 3000)
    assert client.get("/", headers={"host": host(agent_id), "cookie": f"echo_preview={stranger}"}).status_code == 403
    value = cookie_from(client, agent_id, start(client, agent_id)).split(";")[0]
    assert client.get("/", headers={"host": host(agent_id), "cookie": value}).status_code == 200
    client.delete(f"/api/agents/{agent_id}")
    assert client.get("/", headers={"host": host(agent_id), "cookie": value}).status_code == 403


def test_a_preview_host_never_reaches_the_app(agent, client, fake_runner):
    agent_id, _ = agent
    r = client.get("/api/health", headers={"host": host(agent_id)})
    assert r.status_code == 403 and "content-security-policy" not in r.headers
    r = client.get("/", headers={"host": "preview.localhost:8000"})
    assert r.status_code == 404 and r.text == "There is no preview here."
    # And the app's host never reaches the preview handler.
    r = client.get("/.echo-preview/start", params={"token": "x"})
    assert r.status_code == 404 and r.json()["success"] is False


def test_the_api_refuses_a_post_from_a_preview_page(agent, client):
    agent_id, _ = agent
    r = client.post("/api/agents", json={"name": "x"}, headers={"origin": f"http://{host(agent_id)}"})
    assert (r.status_code, r.json()["error"]["code"]) == (403, "bad_origin")


def test_the_app_may_frame_previews_only(tmp_path, on, fake_runner):
    from main import create_app

    web = tmp_path / "dist"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html>")
    with TestClient(create_app(web_dir=web)) as c:
        assert "frame-src http://*.preview.localhost:8000;" in c.get("/").headers["content-security-policy"]


def test_previews_off(client, fake_runner):
    sign_in_as(client)
    agent_id = client.post("/api/agents", json={"name": "Site"}).json()["data"]["id"]
    r = client.post(f"/api/agents/{agent_id}/preview", json={"port": 3000})
    assert (r.status_code, r.json()["error"]["code"]) == (404, "preview_off")
    # A preview-looking host is just another host for the app.
    assert client.get("/api/health", headers={"host": host(agent_id)}).status_code == 200


def test_a_chunked_body_over_the_cap_is_refused(agent, client, fake_runner):
    agent_id, _ = agent
    value = cookie_from(client, agent_id, start(client, agent_id)).split(";")[0]
    chunks = (b"x" * 1024 * 1024 for _ in range(11))
    r = client.post("/upload", content=chunks, headers={"host": host(agent_id), "cookie": value})
    assert r.status_code == 413 and fake_runner.previews == []


def test_a_runner_refusal_reads_as_a_page(agent, client, fake_runner):
    agent_id, _ = agent
    value = cookie_from(client, agent_id, start(client, agent_id)).split(";")[0]
    refusal = b'{"success": false, "error": {"code": "upstream_unreachable", "message": "Nothing answered on port 3000.", "details": null}}'
    fake_runner.preview_answer = (502, [("content-type", "application/json")], refusal)
    r = client.get("/", headers={"host": host(agent_id), "cookie": value})
    assert r.status_code == 502 and r.headers["content-type"].startswith("text/html") and "Nothing answered on port 3000." in r.text
    # The agent's own server's JSON errors pass through untouched.
    own = b'{"error": "not found"}'
    fake_runner.preview_answer = (404, [("content-type", "application/json")], own)
    r = client.get("/", headers={"host": host(agent_id), "cookie": value})
    assert r.status_code == 404 and r.content == own
