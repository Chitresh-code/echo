"""Who may call what: every route but the public ones needs a session, a user sees only their own
workspaces, and a state-changing request from another site is refused."""

import pytest

from apps.accounts.services.session_service import COOKIE
from tests.helpers.accounts import sign_in_as

PUBLIC = {"/api/health", "/api/auth/login", "/api/auth/callback", "/api/auth/logout"}
ID = "c" * 32


def test_every_route_but_the_public_ones_needs_a_session(client, fake_runner):
    # Every API route is in the OpenAPI document, so a new route is walked without listing it here.
    paths = {p: ops for p, ops in client.get("/api/openapi.json").json()["paths"].items() if p not in PUBLIC}
    assert len(paths) >= 8
    for template, operations in paths.items():
        path = template.replace("{workspace_id}", ID).replace("{chat_id}", ID)
        for method in operations:
            r = client.request(method, path, params={"path": "a.txt"}, json={"path": "a.txt", "content": "x", "prompt": "hi"})
            assert (r.status_code, r.json()["error"]["code"]) == (401, "not_signed_in"), f"{method} {template}"
    assert fake_runner.requests == []


def test_a_user_cannot_reach_another_users_workspace(client, fake_runner):
    sign_in_as(client, "ada")
    ws = client.post("/api/workspaces").json()["data"]["id"]
    ada = client.cookies[COOKIE]

    sign_in_as(client, "bob")
    assert client.get("/api/workspaces").json()["data"] == []
    fake_runner.reset()
    for method, path, kwargs in [
        ("GET", f"/api/workspaces/{ws}/tree", {}),
        ("GET", f"/api/workspaces/{ws}/file", {"params": {"path": "a.txt"}}),
        ("PUT", f"/api/workspaces/{ws}/file", {"json": {"path": "a.txt", "content": "x"}}),
        ("GET", f"/api/workspaces/{ws}/git/status", {}),
        ("GET", f"/api/workspaces/{ws}/git/file", {"params": {"path": "a.txt"}}),
        ("POST", f"/api/workspaces/{ws}/chats", {}),
        ("POST", f"/api/workspaces/{ws}/chats/{ID}/turns", {"json": {"prompt": "hi", "credential_id": ID, "model": "m"}}),
    ]:
        r = client.request(method, path, **kwargs)
        assert (r.status_code, r.json()["error"]["code"]) == (404, "workspace_not_found"), f"{method} {path}"
    assert fake_runner.requests == []

    client.cookies.set(COOKIE, ada)
    assert client.get("/api/workspaces").json()["data"] == [{"id": ws}]


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Origin": "null"},
    {"Origin": "http://testserver.evil.example"},
    {"Referer": "https://evil.example/page"},
])
def test_a_request_from_another_site_is_refused(client, fake_runner, headers):
    sign_in_as(client)
    for method, path in [("POST", "/api/workspaces"), ("POST", "/api/auth/logout")]:
        r = client.request(method, path, headers=headers)
        assert (r.status_code, r.json()["error"]["code"]) == (403, "bad_origin")
    assert fake_runner.requests == [] and client.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize("headers", [{"Origin": "http://testserver"}, {"Referer": "http://TESTSERVER/api/docs"}, {}])
def test_echos_own_pages_and_non_browser_clients_pass(client, fake_runner, headers):
    sign_in_as(client)
    assert client.post("/api/workspaces", headers=headers).status_code == 200


def test_reads_are_not_origin_checked(client):
    sign_in_as(client)
    assert client.get("/api/auth/me", headers={"Origin": "https://evil.example"}).status_code == 200
