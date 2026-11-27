"""Stored MCP servers: what is kept, what is shown, the limits, and who can reach them."""

import sqlite3

import pytest

from apps.accounts.services.session_service import COOKIE
from apps.mcp.services import connect, tools
from core.config import get_settings
from core.db import db_path
from tests.helpers.accounts import sign_in_as

SECRET = "mcp-header-secret-value-7Qp"
REMOTE = {"name": "linear", "kind": "remote", "url": "https://mcp.example.com/mcp", "auth": "headers", "headers": {"X-Api-Key": SECRET}}
LOCAL = {"name": "files", "kind": "local", "command": "npx", "args": ["-y", "server"], "env": {"TOKEN": SECRET}}


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    # Connecting is tested in test_connect.py; here a remote server answers with no tools.
    async def listed(server):
        return []

    monkeypatch.setattr(connect, "list_tools", listed)


def add(client, **body):
    return client.post("/api/mcp-servers", json=body)


def data(r):
    assert r.status_code == 200, r.text
    return r.json()["data"]


def code(r):
    return r.status_code, r.json()["error"]["code"]


def stored_secrets():
    with sqlite3.connect(db_path(get_settings().data_dir)) as db:
        return [row[0] for row in db.execute("select secret from mcp_servers")]


def test_add_and_list_never_show_or_store_a_secret_plainly(client, user):
    remote, local = data(add(client, **REMOTE)), data(add(client, **LOCAL))
    assert remote["header_names"] == ["X-Api-Key"] and remote["status"] == "ok" and remote["tools"] == []
    assert local["env_names"] == ["TOKEN"] and local["args"] == ["-y", "server"] and local["url"] is None
    listed = client.get("/api/mcp-servers")
    assert [s["name"] for s in data(listed)] == ["files", "linear"]
    for response in (listed,):
        assert SECRET not in response.text
    assert all(secret and SECRET.encode() not in secret for secret in stored_secrets())


def test_oauth_servers_wait_for_a_connection_and_keep_a_preregistered_client(client, user):
    server = data(add(client, name="sentry", kind="remote", url="https://mcp.sentry.dev/mcp", auth="oauth", client_id="abc", client_secret=SECRET))
    assert server["status"] == "needs_auth" and server["preregistered"] is True and SECRET not in str(server)
    plain = data(add(client, name="plain", kind="remote", url="https://mcp.example.com/", auth="none"))
    # Kept as typed, trailing slash and all.
    assert plain["url"] == "https://mcp.example.com/" and plain["preregistered"] is False and stored_secrets()[-1] is None


@pytest.mark.parametrize("body", [
    {**REMOTE, "name": "Linear"},
    {**REMOTE, "name": "1linear"},
    {**REMOTE, "name": "a" * 21},
    {**REMOTE, "kind": "other"},
    {**REMOTE, "command": "npx"},
    {**REMOTE, "url": None},
    {**REMOTE, "auth": "none"},
    {**REMOTE, "headers": {}},
    {**REMOTE, "headers": {"Bad Name": "x"}},
    {**REMOTE, "headers": {"Host": "x"}},
    {**REMOTE, "headers": {"Mcp-Session-Id": "x"}},
    {**REMOTE, "headers": {"X-Key": "a\r\nInjected: 1"}},
    {**REMOTE, "headers": {f"X-{i}": "v" for i in range(11)}},
    {**REMOTE, "headers": {"X-Key": "v" * 4001}},
    {**REMOTE, "client_id": "abc"},
    {**REMOTE, "auth": "oauth", "headers": {"Authorization": "x"}},
    {**REMOTE, "auth": "oauth", "headers": None, "client_secret": "s"},
    {**REMOTE, "url": "u" * 501},
    {**LOCAL, "url": "https://x.example"},
    {**LOCAL, "command": ""},
    {**LOCAL, "command": None},
    {**LOCAL, "args": ["x"] * 51},
    {**LOCAL, "args": ["x" * 1001]},
    {**LOCAL, "env": {"1BAD": "x"}},
    {**LOCAL, "env": {f"V{i}": "x" for i in range(21)}},
])
def test_invalid_servers_are_refused(client, user, body):
    assert add(client, **body).status_code == 422
    assert data(client.get("/api/mcp-servers")) == []


@pytest.mark.parametrize("url", ["http://mcp.example.com/mcp", "https://user:pw@mcp.example.com/", "https://mcp.example.com/?key=1", "mcp.example.com"])
def test_a_remote_url_must_be_plain_https(client, user, url):
    assert code(add(client, **{**REMOTE, "url": url})) == (400, "invalid_mcp_url")


def test_the_server_limit_and_a_taken_name(client, user, monkeypatch):
    data(add(client, **REMOTE))
    assert code(add(client, **{**LOCAL, "name": "linear"})) == (409, "mcp_server_name_taken")
    from apps.mcp.services import mcp_service
    monkeypatch.setattr(mcp_service, "MAX_SERVERS", 2)
    data(add(client, **LOCAL))
    assert code(add(client, **{**LOCAL, "name": "third"})) == (409, "mcp_server_limit_reached")


def test_secrets_are_replaced_per_kind(client, user):
    remote, local = data(add(client, **REMOTE)), data(add(client, **LOCAL))
    changed = data(client.patch(f"/api/mcp-servers/{remote['id']}", json={"headers": {"Authorization": "Bearer new"}}))
    assert changed["header_names"] == ["Authorization"]
    assert data(client.patch(f"/api/mcp-servers/{local['id']}", json={"env": {}}))["env_names"] == []
    assert code(client.patch(f"/api/mcp-servers/{remote['id']}", json={"env": {"A": "b"}})) == (400, "secret_not_supported")
    assert code(client.patch(f"/api/mcp-servers/{local['id']}", json={"headers": {"A": "b"}})) == (400, "secret_not_supported")
    assert client.patch(f"/api/mcp-servers/{remote['id']}", json={"headers": {"Host": "x"}}).status_code == 422
    assert client.patch(f"/api/mcp-servers/{remote['id']}", json={}).status_code == 422


def set_pending(server_id, pending):
    import json
    with sqlite3.connect(db_path(get_settings().data_dir)) as db:
        db.execute("update mcp_servers set pending_tools = ?, status = 'tools_changed' where id = ?", (json.dumps(pending), server_id))


def test_changed_tools_are_accepted_only_by_the_hash_waiting(client, user):
    server = data(add(client, **REMOTE))
    pending = tools.clean("linear", [{"name": "search", "description": "Find issues", "input_schema": {"type": "object"}, "annotations": {"readOnlyHint": True}}])
    review = f"/api/mcp-servers/{server['id']}/tools/review"
    assert code(client.post(review, json={"hash": "0" * 64})) == (409, "tools_moved_on")
    set_pending(server["id"], pending)
    shown = data(client.get("/api/mcp-servers"))[0]
    assert shown["status"] == "tools_changed" and shown["pending_tools"] == [{"name": "search", "description": "Find issues", "hints": {"readOnlyHint": True}}]
    assert code(client.post(review, json={"hash": "0" * 64})) == (409, "tools_moved_on")
    accepted = data(client.post(review, json={"hash": shown["pending_hash"]}))
    assert accepted["status"] == "ok" and accepted["pending_tools"] is None and [t["name"] for t in accepted["tools"]] == ["search"]


def test_agents_get_only_their_owners_servers(client):
    sign_in_as(client, "ada")
    agent = data(client.post("/api/agents", json={"name": "A"}))["id"]
    mine = data(add(client, **REMOTE))["id"]
    ada_cookie = client.cookies[COOKIE]

    sign_in_as(client, "bob")
    bobs = data(add(client, **LOCAL))["id"]
    for method, path, kwargs in [
        ("PATCH", f"/api/mcp-servers/{mine}", {"json": {"headers": {"A": "b"}}}),
        ("DELETE", f"/api/mcp-servers/{mine}", {}),
        ("POST", f"/api/mcp-servers/{mine}/tools/review", {"json": {"hash": "0" * 64}}),
    ]:
        assert code(client.request(method, path, **kwargs)) == (404, "mcp_server_not_found"), f"{method} {path}"
    assert [s["id"] for s in data(client.get("/api/mcp-servers"))] == [bobs]

    client.cookies.set(COOKIE, ada_cookie)
    servers = f"/api/agents/{agent}/mcp-servers"
    assert code(client.put(servers, json={"server_ids": [mine, bobs]})) == (404, "mcp_server_not_found")
    assert data(client.get(servers)) == []
    assert [s["id"] for s in data(client.put(servers, json={"server_ids": [mine, mine]}))] == [mine]


def test_too_many_servers_for_an_agent(client, user, monkeypatch):
    from apps.mcp.services import mcp_service
    monkeypatch.setattr(mcp_service, "MAX_PER_AGENT", 1)
    agent = data(client.post("/api/agents", json={"name": "A"}))["id"]
    ids = [data(add(client, **REMOTE))["id"], data(add(client, **LOCAL))["id"]]
    assert code(client.put(f"/api/agents/{agent}/mcp-servers", json={"server_ids": ids})) == (400, "too_many_mcp_servers")


def assignments():
    with sqlite3.connect(db_path(get_settings().data_dir)) as db:
        return db.execute("select count(*) from agent_mcp_servers").fetchone()[0]


def test_deleting_a_server_an_agent_or_a_user_removes_the_assignments(client, user, fake_runner):
    agent = data(client.post("/api/agents", json={"name": "A"}))["id"]
    remote, local = data(add(client, **REMOTE))["id"], data(add(client, **LOCAL))["id"]
    data(client.put(f"/api/agents/{agent}/mcp-servers", json={"server_ids": [remote, local]}))
    data(client.delete(f"/api/mcp-servers/{remote}"))
    assert [s["id"] for s in data(client.get(f"/api/agents/{agent}/mcp-servers"))] == [local]
    data(client.delete(f"/api/agents/{agent}"))
    assert assignments() == 0

    agent = data(client.post("/api/agents", json={"name": "B"}))["id"]
    data(client.put(f"/api/agents/{agent}/mcp-servers", json={"server_ids": [local]}))
    with sqlite3.connect(db_path(get_settings().data_dir)) as db:
        db.execute("pragma foreign_keys = on")
        db.execute("delete from agents")
        db.execute("delete from users")
        assert db.execute("select count(*) from mcp_servers").fetchone()[0] == 0
        assert db.execute("select count(*) from agent_mcp_servers").fetchone()[0] == 0


def test_clean_drops_bad_and_repeated_names_and_cuts_long_descriptions():
    listed = [
        {"name": "search", "description": "d" * 3000},
        {"name": "search", "description": "again"},
        {"name": "has space"},
        {"name": "x" * 60},
        {"name": None},
        {"name": "ok.dot-dash", "description": 5},
    ] + [{"name": f"t{i}"} for i in range(200)]
    cleaned = tools.clean("linear", listed)
    assert [t["name"] for t in cleaned[:2]] == ["search", "ok.dot-dash"]
    assert len(cleaned[0]["description"]) == tools.MAX_DESCRIPTION and cleaned[1]["description"] == ""
    assert len(cleaned) == tools.MAX_TOOLS


def test_digest_is_stable_under_key_order_and_changes_with_content():
    a = [{"name": "s", "description": "d", "input_schema": {"a": 1, "b": 2}, "annotations": None}]
    b = [{"annotations": None, "input_schema": {"b": 2, "a": 1}, "description": "d", "name": "s"}]
    assert tools.digest(a) == tools.digest(b)
    assert tools.digest(a) != tools.digest([{**a[0], "description": "changed"}])
