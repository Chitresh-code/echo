"""Remote MCP servers for real: an MCP server from the SDK runs on localhost, and the guarded client
is swapped for one that reaches it, since the guard refuses local addresses."""

import asyncio
import json
import logging
import socket
import threading
import time

import httpx2
import pytest
import uvicorn
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import PlainTextResponse

from apps.chat.services import agent_factory, approvals, turn_service
from apps.mcp.services import connect, tools
from core.config import get_settings
from tests.chat.test_turns import WS, wait_for
from tests.helpers.scripted_model import ScriptedModel
from tests.helpers.turns import FakeWriter

SECRET = "mcp-key-9fK2"
MARKER = "private-input-7Hq"

server = MCPServer("docs")
seen = {"headers": []}


@server.tool(annotations={"readOnlyHint": True})
def search(query: str) -> str:
    """Searches the docs."""
    return f"found {query}"


@server.tool()
def long() -> str:
    return "x" * (tools.MAX_RESULT + 5000)


@server.tool()
def fail() -> str:
    raise ValueError("broken")


@server.tool()
def capabilities(ctx: Context) -> str:
    return json.dumps(ctx.client_capabilities.model_dump(exclude_none=True))


def _app():
    inner = server.streamable_http_app(transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    async def app(scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            seen["headers"].append(headers)
            if scope["path"] == "/slow":
                await asyncio.sleep(10)
            if headers.get("x-api-key") != SECRET:
                return await PlainTextResponse("no", status_code=401)(scope, receive, send)
        await inner(scope, receive, send)

    return app


@pytest.fixture(scope="module")
def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    running = uvicorn.Server(uvicorn.Config(_app(), port=free, log_level="warning", lifespan="on"))
    threading.Thread(target=running.run, daemon=True).start()
    while not running.started:
        time.sleep(0.05)
    yield free
    running.should_exit = True


class ToLocal(httpx2.AsyncBaseTransport):
    """Sends every request to the test server, keeping its path and headers."""

    def __init__(self, port):
        self.port, self.inner = port, httpx2.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        # Put the address back afterwards: an auth flow sends the same request again, and the
        # guarded client's https check must see the address the SDK chose, not this one.
        url, request.url = request.url, request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        try:
            return await self.inner.handle_async_request(request)
        finally:
            request.url = url


@pytest.fixture
def local(monkeypatch, port):
    monkeypatch.setattr(connect, "_http", lambda headers, auth=None: httpx2.AsyncClient(headers=headers, auth=auth, transport=ToLocal(port)))
    seen["headers"].clear()


def remote(name="docs", path="/mcp", key=SECRET, tools_hash=None, status="ok"):
    return connect.TurnServer("s-" + name, name, f"https://mcp.test{path}", status, {"X-Api-Key": key}, tools_hash)


def body(name="docs", key=SECRET, path="/mcp"):
    return {"name": name, "kind": "remote", "url": f"https://mcp.test{path}", "auth": "headers", "headers": {"X-Api-Key": key}}


def test_adding_lists_and_stores_the_tools(client, user, local):
    response = client.post("/api/mcp-servers", json=body())
    added = response.json()["data"]
    assert {t["name"] for t in added["tools"]} == {"search", "long", "fail", "capabilities"}
    assert next(t for t in added["tools"] if t["name"] == "search")["hints"] == {"readOnlyHint": True}
    assert seen["headers"] and all(h.get("x-api-key") == SECRET for h in seen["headers"])
    assert SECRET not in response.text


def test_a_refused_sign_in_and_a_down_server_are_refused(client, user, local):
    for sent, expected in [(body(key="wrong"), (400, "mcp_auth_failed")), (body(path="/missing"), (502, "mcp_server_error"))]:
        response = client.post("/api/mcp-servers", json=sent)
        assert (response.status_code, response.json()["error"]["code"]) == expected
    assert client.get("/api/mcp-servers").json()["data"] == []


def test_new_headers_are_tried_before_they_are_kept(client, user, local):
    added = client.post("/api/mcp-servers", json=body()).json()["data"]
    response = client.patch(f"/api/mcp-servers/{added['id']}", json={"headers": {"X-Api-Key": "wrong"}})
    assert response.json()["error"]["code"] == "mcp_auth_failed"


def test_a_local_address_is_refused_by_the_guard(client, user):
    response = client.post("/api/mcp-servers", json={**body(), "url": "https://127.0.0.1/mcp"})
    assert (response.status_code, response.json()["error"]["code"]) == (400, "endpoint_not_allowed")


async def call(client, tool, arguments=None):
    found = next(t for t in await client.load_tools() if t.tool_name == f"docs_{tool}")
    events = [e async for e in found.stream({"toolUseId": "1", "name": found.tool_name, "input": arguments or {}}, {})]
    return events[-1].tool_result


async def test_results_are_capped_errors_stay_errors_and_calls_log_no_data(local, caplog):
    mcp = connect.TurnMcp([remote()], "u1", WS)
    assert await mcp.start() == []
    try:
        client = mcp.clients[0]
        cut = await call(client, "long")
        assert cut["status"] == "success" and "structuredContent" not in cut
        assert sum(len(c["text"]) for c in cut["content"][:-1]) == tools.MAX_RESULT and "cut this result" in cut["content"][-1]["text"]
        assert (await call(client, "fail"))["status"] == "error"
        with caplog.at_level(logging.INFO):
            found = await call(client, "search", {"query": MARKER})
        assert MARKER in found["content"][0]["text"]
        assert "tool=search" in caplog.text and MARKER not in caplog.text
        # No sampling, elicitation or roots: a server cannot ask the agent or the user for anything.
        assert json.loads((await call(client, "capabilities"))["content"][0]["text"]) == {}
    finally:
        await mcp.stop()


async def test_changed_tools_and_failures_leave_a_server_out(local, monkeypatch):
    monkeypatch.setattr(connect, "STARTUP_TIMEOUT", 1)
    servers = [
        remote("changed", tools_hash="0" * 64),
        remote("denied", key="wrong"),
        remote("slow", path="/slow"),
        remote("oauth", status="needs_auth"),
        remote("first"),
    ]
    mcp = connect.TurnMcp(servers, "u1", WS)
    gone = {u.name: u.reason for u in await mcp.start()}
    await mcp.stop()
    assert gone == {
        "changed": connect.REASONS["tools_changed"],
        "denied": connect.REASONS["auth"],
        "slow": connect.REASONS["timeout"],
        "oauth": connect.REASONS["needs_auth"],
    }
    assert mcp.changes["s-changed"]["status"] == "tools_changed" and len(mcp.changes["s-changed"]["pending_tools"]) == 4
    # A first list is taken as the reviewed one.
    assert mcp.changes["s-first"]["tools_hash"] == tools.digest(mcp.changes["s-first"]["tools"])


async def test_starting_a_server_does_not_block_the_event_loop(local, monkeypatch):
    monkeypatch.setattr(connect, "STARTUP_TIMEOUT", 1)
    ticks = 0

    async def tick():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    ticker = asyncio.create_task(tick())
    await connect.TurnMcp([remote("slow", path="/slow")], "u1", WS).start()
    ticker.cancel()
    assert ticks >= 10


def maker(model, chat):
    return lambda delegation, gate, mcp: agent_factory.build_agent(
        get_settings(), WS, chat, model, "anthropic/claude-sonnet-5-5", model, "Test agent", "", delegation=delegation, approvals=gate, mcp=mcp
    )


def start(chat, model, servers, writer=None):
    mcp = connect.TurnMcp(servers, "u1", WS)
    turn = turn_service.start_turn(writer or FakeWriter(), WS, chat, maker(model, chat), "go", 60, title="go", user_id="u1", mcp=mcp)
    return turn, mcp


async def test_a_turn_calls_an_mcp_tool_after_approval(local, fake_runner):
    model = ScriptedModel([[("tool", "docs_search", {"query": "pricing"})], [("text", "done")]])
    writer = FakeWriter()
    turn, mcp = start("a" * 32, model, [remote(), remote("broken", key="wrong")], writer)
    await wait_for(lambda: any(e == "approval_needed" for e, _ in turn.events))
    card = next(d for e, d in turn.events if e == "approval_needed")
    assert card["tool"] == "docs_search" and card["server"] == "docs" and card["hints"] == {"readOnlyHint": True}
    approvals.answer(card["id"], WS, "u1", "allow")
    await asyncio.wait_for(turn.ended.wait(), 10)

    assert turn.status == "done"
    assert [d for e, d in turn.events if e == "mcp_unavailable"] == [{"server": "broken", "reason": connect.REASONS["auth"], "detail": ""}]
    assert "docs_search" in model.tool_names[0] and not any(n.startswith("broken_") for n in model.tool_names[0])
    prompt = model.system_prompts[0]
    assert "connected: docs." in prompt and f"broken is unavailable this turn: {connect.REASONS['auth']}" in prompt
    results = [c["text"] for m in model.all_messages[1] for b in m["content"] if "toolResult" in b for c in b["toolResult"]["content"]]
    assert results == ["found pricing"]
    # The header went to the server only.
    assert SECRET not in json.dumps(model.all_messages) + json.dumps(model.system_prompts) + json.dumps(turn.events)
    assert mcp.clients == [] and len(writer.writes) > 0


@pytest.mark.parametrize("ending", ["failed", "stopped"])
async def test_clients_are_stopped_however_the_turn_ends(local, fake_runner, monkeypatch, ending):
    closed = []
    original = connect.EchoClient.close
    monkeypatch.setattr(connect.EchoClient, "close", lambda self: (closed.append(self.server.name), original(self)))
    if ending == "failed":

        def make(delegation, gate, mcp):
            raise RuntimeError("boom")

        mcp = connect.TurnMcp([remote()], "u1", WS)
        turn = turn_service.start_turn(FakeWriter(), WS, "c" * 32, make, "go", 60, title="go", user_id="u1", mcp=mcp)
    else:
        turn, mcp = start("d" * 32, ScriptedModel([[("tool", "docs_search", {"query": "q"})], [("text", "done")]]), [remote()])
        await wait_for(lambda: any(e == "approval_needed" for e, _ in turn.events))
        turn_service.stop(turn)
    await asyncio.wait_for(turn.ended.wait(), 10)
    assert "docs" in closed and mcp.clients == []
