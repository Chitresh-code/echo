"""OAuth for remote MCP servers against a fake authorization server and an MCP server that wants its
tokens, both on localhost behind the address rewrite from test_connect."""

import asyncio
import dataclasses
import socket
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from apps.credentials.services import safe_http
from apps.mcp.services import connect, mcp_service, oauth
from core.config import get_settings
from core.db import create_engine, db_path
from tests.chat.test_turns import WS
from tests.mcp.test_connect import ToLocal

AS = "https://auth.test"
MCP_URL = "https://mcp.test/mcp"
LEAK = "provider-text-Zq8"

server = MCPServer("linear")


@server.tool(annotations={"readOnlyHint": True})
def issues() -> str:
    return "three issues"


fake: dict = {}


def reset(**overrides):
    fake.clear()
    fake.update(
        s256=True, cimd=False, authorize=f"{AS}/authorize", www_auth=True, valid={"at-1"}, refresh_ok=True, need_scope=None,
        registered=[], authorized=[], token_requests=[], seen_auth=[], **overrides,
    )


async def as_app(scope, receive, send):
    request = Request(scope, receive)
    path = scope["path"]
    if path.startswith("/.well-known/oauth-protected-resource"):
        response = JSONResponse({"resource": MCP_URL, "authorization_servers": [AS], "scopes_supported": ["read"]})
    elif path == "/.well-known/oauth-authorization-server" and fake.get("as_meta", True):
        response = JSONResponse({
            "issuer": AS, "authorization_endpoint": fake["authorize"], "token_endpoint": fake.get("token", f"{AS}/token"),
            "registration_endpoint": f"{AS}/register", "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"] if fake["s256"] else ["plain"],
            "client_id_metadata_document_supported": fake["cimd"],
        })
    elif path == "/register":
        body = await request.json()
        fake["registered"].append(body)
        response = JSONResponse({**body, "client_id": "reg-1"}, status_code=201)
    elif path == "/token":
        form = dict(await request.form())
        fake["token_requests"].append(form)
        if form["grant_type"] == "authorization_code" and form.get("code") == "good" and form.get("code_verifier"):
            fake["valid"].add("at-1")
            response = JSONResponse({"access_token": "at-1", "token_type": "Bearer", "expires_in": 3600, "refresh_token": "rt-1", "scope": "read"})
        elif form["grant_type"] == "refresh_token" and fake["refresh_ok"]:
            fake["valid"].add("at-2")
            response = JSONResponse({"access_token": "at-2", "token_type": "Bearer", "expires_in": 3600, "refresh_token": "rt-2", "scope": "read"})
        else:
            response = JSONResponse({"error": "invalid_grant", "error_description": LEAK}, status_code=400)
    else:
        response = PlainTextResponse("no", status_code=404)
    await response(scope, receive, send)


def mcp_app():
    inner = server.streamable_http_app(transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return await inner(scope, receive, send)
        host = dict(scope["headers"]).get(b"x-test-host", b"").decode()
        if host == "auth.test" or scope["path"].startswith("/.well-known"):
            return await as_app(scope, receive, send)
        token = dict(scope["headers"]).get(b"authorization", b"").decode().removeprefix("Bearer ")
        fake["seen_auth"].append(token)
        challenge = 'Bearer resource_metadata="https://mcp.test/.well-known/oauth-protected-resource/mcp"' if fake["www_auth"] else "Bearer"
        if token not in fake["valid"]:
            return await PlainTextResponse("no", status_code=401, headers={"WWW-Authenticate": challenge})(scope, receive, send)
        if fake["need_scope"] and scope["path"] == "/mcp" and scope["method"] == "POST":
            body = b""
            more = True
            while more:
                message = await receive()
                body += message.get("body", b"")
                more = message.get("more_body", False)
            if b"tools/call" in body:
                header = f'Bearer error="insufficient_scope", scope="{fake["need_scope"]}"'
                return await PlainTextResponse("no", status_code=403, headers={"WWW-Authenticate": header})(scope, receive, send)
            sent = [False]

            async def replay():
                if not sent[0]:
                    sent[0] = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            return await inner(scope, replay, send)
        await inner(scope, receive, send)

    return app


class Both(ToLocal):
    """ToLocal, telling the test app which host a request was for."""

    async def handle_async_request(self, request):
        request.headers["x-test-host"] = request.url.host
        return await super().handle_async_request(request)


@pytest.fixture(scope="module")
def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    running = uvicorn.Server(uvicorn.Config(mcp_app(), port=free, log_level="warning", lifespan="on"))
    threading.Thread(target=running.run, daemon=True).start()
    while not running.started:
        time.sleep(0.05)
    yield free
    running.should_exit = True


@pytest.fixture
def local(monkeypatch, port):
    # With the guarded client's https check, so a plain http address a server names is refused here too.
    monkeypatch.setattr(connect, "_http", lambda headers, auth=None: httpx2.AsyncClient(
        headers=headers, auth=auth, transport=Both(port), event_hooks={"request": [safe_http._https_only]}))
    reset()
    oauth._flows.clear()


def data(r):
    assert r.status_code == 200, r.text
    return r.json()["data"]


def add(client, **extra):
    return data(client.post("/api/mcp-servers", json={"name": "linear", "kind": "remote", "url": MCP_URL, "auth": "oauth", **extra}))


def authorize(client, server_id):
    url = data(client.post(f"/api/mcp-servers/{server_id}/oauth"))["authorize_url"]
    return url, {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def callback(client, **params):
    response = client.get("/api/mcp/oauth/callback", params=params, follow_redirects=False)
    assert response.status_code == 302
    return response.headers["location"]


def stored(server_id):
    with sqlite3.connect(db_path(get_settings().data_dir)) as db:
        return db.execute("select secret, status from mcp_servers where id = ?", (server_id,)).fetchone()


def blob(server_id):
    return mcp_service._open(get_settings(), stored(server_id)[0])


def connected(client):
    server = add(client)
    _, query = authorize(client, server["id"])
    assert callback(client, code="good", state=query["state"], iss=AS) == f"/mcp?connected={server['id']}"
    return server


@pytest.mark.parametrize("www_auth", [True, False])
def test_connecting_registers_echo_and_stores_encrypted_tokens(client, user, local, www_auth):
    fake["www_auth"] = www_auth
    server = add(client)
    url, query = authorize(client, server["id"])
    assert url.startswith(f"{AS}/authorize?")
    assert query["code_challenge_method"] == "S256" and query["resource"] == MCP_URL and query["client_id"] == "reg-1"
    assert query["redirect_uri"] == "http://testserver" + oauth.CALLBACK_PATH and query["state"]
    # Registered as a web app with the one callback, since the public URL is not https.
    [registered] = fake["registered"]
    assert registered["application_type"] == "web" and registered["redirect_uris"] == ["http://testserver" + oauth.CALLBACK_PATH]

    assert callback(client, code="good", state=query["state"], iss=AS) == f"/mcp?connected={server['id']}"
    secret, status = stored(server["id"])
    assert status == "ok" and b"at-1" not in secret and b"rt-1" not in secret
    assert blob(server["id"])["tokens"]["access_token"] == "at-1"
    listed = data(client.get("/api/mcp-servers"))[0]
    assert listed["status"] == "ok" and [t["name"] for t in listed["tools"]] == ["issues"]


def test_a_preregistered_client_is_used_without_registering(client, user, local):
    server = add(client, client_id="pre-1")
    _, query = authorize(client, server["id"])
    assert query["client_id"] == "pre-1" and fake["registered"] == []


async def test_with_an_https_public_url_the_client_id_is_the_metadata_document(local):
    fake["cimd"] = True
    settings = dataclasses.replace(get_settings(), public_url="https://echo.example.com")
    provider = oauth.Guarded("linear", MCP_URL, settings, {})
    url = await oauth.start("u1", "s1", provider, lambda _: connect.list_on_loop(connect.TurnServer("s1", "linear", MCP_URL, "ok", auth=provider)))
    oauth._drop(parse_qs(urlparse(url).query)["state"][0])
    assert parse_qs(urlparse(url).query)["client_id"] == ["https://echo.example.com" + oauth.CLIENT_PATH]
    assert fake["registered"] == []
    document = oauth.metadata_document(settings)
    assert document["client_id"] == "https://echo.example.com" + oauth.CLIENT_PATH
    assert document["redirect_uris"] == ["https://echo.example.com" + oauth.CALLBACK_PATH]


def test_the_metadata_document_is_public(client):
    response = client.get(oauth.CLIENT_PATH)
    assert response.status_code == 200 and response.json()["client_name"] == "Echo"


@pytest.mark.parametrize("change", [{"s256": False}, {"authorize": "http://auth.test/authorize"}])
def test_an_authorization_server_without_its_protections_is_refused(client, user, local, change):
    fake.update(change)
    server = add(client)
    response = client.post(f"/api/mcp-servers/{server['id']}/oauth")
    assert (response.status_code, response.json()["error"]["code"]) == (400, "oauth_unsupported")


def test_a_plain_http_token_endpoint_gets_no_code(client, user, local):
    fake.update(token="http://auth.test/token")
    server = add(client)
    _, query = authorize(client, server["id"])
    assert callback(client, code="good", state=query["state"], iss=AS) == "/mcp?error=endpoint_not_allowed"
    assert fake["token_requests"] == [] and stored(server["id"])[1] == "needs_auth"


def test_a_server_without_oauth_metadata_says_so(client, user, local):
    fake.update(as_meta=False)
    server = add(client)
    response = client.post(f"/api/mcp-servers/{server['id']}/oauth")
    assert (response.status_code, response.json()["error"]["code"]) == (400, "oauth_no_metadata")
    assert fake["authorized"] == [] and fake["token_requests"] == []


def test_a_bad_callback_is_refused(client, user, local):
    server = add(client)
    _, query = authorize(client, server["id"])
    assert callback(client, code="good", state="unknown") == "/mcp?error=oauth_state_invalid"
    # A mismatched issuer ends the flow, and its state cannot be used again.
    assert callback(client, code="good", state=query["state"], iss="https://evil.test/") == "/mcp?error=oauth_failed"
    assert callback(client, code="good", state=query["state"], iss=AS) == "/mcp?error=oauth_state_invalid"
    assert stored(server["id"])[1] == "needs_auth"


def test_an_expired_or_another_users_state_is_refused(client, user, local):
    from tests.helpers.accounts import sign_in_as

    server = add(client)
    _, query = authorize(client, server["id"])
    cookie = dict(client.cookies)
    sign_in_as(client, "mallory")
    assert callback(client, code="good", state=query["state"]) == "/mcp?error=oauth_state_invalid"
    for name, value in cookie.items():
        client.cookies.set(name, value)
    # Still waiting for its owner after the other user's attempt.
    oauth._flows[query["state"]].expires = 0
    assert callback(client, code="good", state=query["state"]) == "/mcp?error=oauth_state_invalid"


def test_a_provider_error_is_denied_without_its_text(client, user, local):
    server = add(client)
    _, query = authorize(client, server["id"])
    location = callback(client, error="access_denied", error_description=LEAK, state=query["state"])
    assert location == "/mcp?error=oauth_denied" and LEAK not in location


def turn_server(server_id) -> connect.TurnServer:
    settings = get_settings()
    with sqlite3.connect(db_path(settings.data_dir)) as db:
        db.row_factory = sqlite3.Row
        row = dict(db.execute("select * from mcp_servers where id = ?", (server_id,)).fetchone())
    secret = mcp_service._open(settings, row["secret"])
    return connect.TurnServer(row["id"], row["name"], row["url"], row["status"], {}, row["tools_hash"], oauth.Guarded("linear", row["url"], settings, secret))


async def run_turn(server: connect.TurnServer, call=False):
    mcp = connect.TurnMcp([server], "u1", WS)
    unavailable = await mcp.start()
    result = None
    if call and mcp.clients:
        found = (await mcp.clients[0].load_tools())[0]
        events = [e async for e in found.stream({"toolUseId": "1", "name": found.tool_name, "input": {}}, {})]
        result = events[-1].tool_result
    await mcp.stop()
    return mcp, unavailable, result


def owner(server_id):
    with sqlite3.connect(db_path(get_settings().data_dir)) as db:
        return db.execute("select owner_id from mcp_servers where id = ?", (server_id,)).fetchone()[0]


def test_a_turn_uses_the_token_and_writes_a_refreshed_one_back(client, user, local):
    server = connected(client)
    # The token expired: the turn refreshes it and keeps the new one.
    secret = blob(server["id"])
    secret["expires_at"] = time.time() - 10
    save(server["id"], secret)
    fake["valid"] = {"at-2"}
    mcp, unavailable, result = asyncio.run(run_turn(turn_server(server["id"]), call=True))
    assert unavailable == [] and result["content"][0]["text"] == "three issues"
    assert "at-2" in fake["seen_auth"] and mcp.changes[server["id"]]["oauth"]["tokens"]["refresh_token"] == "rt-2"
    asyncio.run(write_back_as(mcp, owner(server["id"])))
    assert blob(server["id"])["tokens"]["access_token"] == "at-2"


def test_a_refused_refresh_needs_a_new_connection(client, user, local):
    server = connected(client)
    secret = blob(server["id"])
    secret["expires_at"] = time.time() - 10
    save(server["id"], secret)
    fake.update(valid=set(), refresh_ok=False)
    mcp, unavailable, _ = asyncio.run(run_turn(turn_server(server["id"])))
    assert [u.reason for u in unavailable] == [connect.REASONS["needs_auth"]]
    asyncio.run(write_back_as(mcp, owner(server["id"])))
    assert stored(server["id"])[1] == "needs_auth"


def test_too_little_scope_fails_the_call_and_reconnect_asks_for_both(client, user, local):
    server = connected(client)
    fake["need_scope"] = "write"
    mcp, unavailable, result = asyncio.run(run_turn(turn_server(server["id"]), call=True))
    assert unavailable == [] and result["status"] == "error"
    assert result["content"][0]["text"] == f"linear cannot be used: {connect.REASONS['needs_scope']}. Tell the user."
    assert mcp.changes[server["id"]]["status"] == "needs_scope"
    asyncio.run(write_back_as(mcp, owner(server["id"])))
    assert stored(server["id"])[1] == "needs_scope"
    _, query = authorize(client, server["id"])
    assert set(query["scope"].split()) == {"read", "write"}


def save(server_id, secret):
    with sqlite3.connect(db_path(get_settings().data_dir)) as db:
        db.execute("update mcp_servers set secret = ? where id = ?", (mcp_service._seal(get_settings(), secret), server_id))


async def write_back_as(mcp, owner_id):
    engine = create_engine(get_settings().data_dir)
    async with async_sessionmaker(engine)() as db:
        await mcp_service.save_changes(get_settings(), owner_id, mcp.changes)(db)
        await db.commit()
    await engine.dispose()
