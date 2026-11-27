"""Connects to a user's MCP servers, remote or local (run in the workspace's jail): for one turn, and once when a server is added to list its
tools. Each server gets a Strands MCPClient named after it, so the harness can hand the same started
client to subagents. The SDK runs every client on a thread and event loop of its own and its calls
block, so they run in worker threads and never on the api's loop.

The tools a turn offers are the ones listed when it started, cleaned and compared with the list the
user reviewed: a server whose tools changed is left out until the user looks at the new list."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import PaginatedRequestParams
from strands.tools.mcp import MCPAgentTool, MCPClient
from strands.types.events import ToolResultEvent

from apps.credentials.services import safe_http
from apps.mcp.services import oauth, runner_stdio, tools
from core.errors import AppError

logger = logging.getLogger(__name__)

# Seconds a server has to accept the connection and list its tools.
STARTUP_TIMEOUT = 20
# One tool call; the SDK cancels the request on the server when it passes.
CALL_TIMEOUT = timedelta(seconds=120)
# Pages of tools read from one server; with MAX_TOOLS kept, more only costs time.
MAX_PAGES = 10

# Why a server is left out of a turn, as the user and the model are told. Never the server's own text.
REASONS = {
    "refused": "its address is not allowed",
    "auth": "it refused the sign-in, so its headers need updating in Connectors",
    "needs_auth": "it needs connecting in Connectors",
    "needs_scope": "it needs more access, so reconnect it in Connectors",
    "tools_changed": "its tools changed and need a review in Connectors",
    "timeout": f"it did not answer within {STARTUP_TIMEOUT} seconds",
    "error": "it failed to start, and the server log has the details",
    "exited": "it exited while starting",
    "runner": "the sandbox could not start it",
}


@dataclass
class TurnServer:
    """A server as a turn uses it, with its secrets decrypted."""

    id: str
    name: str
    url: str
    status: str
    headers: dict[str, str] = field(default_factory=dict)
    # The digest of the reviewed tools; None until the first list is taken as reviewed.
    tools_hash: str | None = None
    # The OAuth provider, holding the server's tokens, for a server that signs in with OAuth.
    auth: oauth.Guarded | None = None
    # How to start a local server; None for a remote one.
    local: runner_stdio.Local | None = None


@dataclass
class Unavailable:
    name: str
    reason: str
    # For the user only, never the model: a local server's own error output, or why the sandbox refused it.
    detail: str = ""


class ConnectFailed(Exception):
    def __init__(self, cause: str):
        super().__init__(cause)
        self.cause = cause


def _http(headers: dict[str, str], auth: httpx2.Auth | None = None) -> httpx2.AsyncClient:
    # The tests swap this for a client that reaches an MCP server on localhost. OAuth's discovery,
    # registration and token requests go through it too, so the address guard covers them.
    return safe_http.client2(headers=headers, auth=auth)


class EchoTool(MCPAgentTool):
    """An MCP tool whose result is capped before the model sees it, and whose calls are logged
    without their input or result, which can hold the user's data."""

    async def stream(self, tool_use, invocation_state, **kwargs):
        client: EchoClient = self.mcp_client
        started = time.monotonic()
        result = await client.call_tool_async(
            tool_use_id=tool_use["toolUseId"],
            name=self.mcp_tool.name,
            arguments=tool_use["input"],
            read_timeout_seconds=self.timeout,
            cancel_signal=getattr(invocation_state.get("agent"), "_cancel_signal", None),
        )
        logger.info(
            "MCP call user=%s agent=%s server=%s tool=%s seconds=%.1f status=%s",
            client.user_id, client.agent_id, client.server.name, self.mcp_tool.name, time.monotonic() - started, result.get("status"),
        )
        if client.server.auth is not None and client.server.auth.needs:
            # The SDK's text for this failure is not meant for the model; this says what to do.
            reason = REASONS[client.server.auth.needs]
            result = {"toolUseId": result["toolUseId"], "status": "error", "content": [{"text": f"{client.server.name} cannot be used: {reason}. Tell the user."}]}
        yield ToolResultEvent(tools.cap_result(result))


class EchoClient(MCPClient):
    def __init__(self, server: TurnServer, user_id: str = "", agent_id: str = ""):
        self.server, self.user_id, self.agent_id = server, user_id, agent_id
        # The SDK reports a 401 or 403 as a bare protocol error, so the status is noted on the way in.
        self.auth_refused = False
        self.offered: list[dict] = []
        super().__init__(self._transport, startup_timeout=STARTUP_TIMEOUT, prefix=server.name, application_name=server.name)

    def _transport(self):
        if self.server.local is not None:
            return runner_stdio.transport(self.server.local)
        # A new HTTP client per connection: it belongs to the loop of the thread that connects.
        http = _http(self.server.headers, self.server.auth)
        http.event_hooks["response"].append(self._note_status)
        return streamable_http_client(self.server.url, http_client=http)

    async def _note_status(self, response: httpx2.Response) -> None:
        if response.status_code in (401, 403):
            self.auth_refused = True

    def connect(self) -> list[dict]:
        """Blocking: starts the client, lists and cleans its tools, and keeps them as the tools it
        hands the agent, so the harness never lists them again mid-turn."""
        try:
            self.start()
        except Exception as exc:
            raise ConnectFailed(self._cause(exc)) from exc
        try:
            listed, token = [], None
            for _ in range(MAX_PAGES):
                page = self.list_tools_sync(token)
                listed.extend(page)
                if (token := page.pagination_token) is None or len(listed) >= tools.MAX_TOOLS * 2:
                    break
            offered = tools.clean(self.server.name, [_described(t.mcp_tool) for t in listed])
            by_name = {t.mcp_tool.name: t.mcp_tool for t in listed}
            self._loaded_tools = [
                EchoTool(by_name[t["name"]].model_copy(update={"description": t["description"]}), self, f"{self.server.name}_{t['name']}", CALL_TIMEOUT)
                for t in offered
            ]
        except Exception as exc:
            self.close()
            raise ConnectFailed(self._cause(exc)) from exc
        self.offered = offered
        return offered

    async def load_tools(self, **kwargs):
        # The list taken in connect(). Since the client is never marked as started for the agent,
        # the agent does not stop it on close either: closing blocks, so the turn does it in a
        # worker thread instead of on the api's loop.
        return self._loaded_tools or []

    def _cause(self, exc: BaseException) -> str:
        if safe_http.refused(exc):
            return "refused"
        if self.server.auth is not None and self.server.auth.needs:
            return self.server.auth.needs
        if self.server.local is not None and self.server.local.exited:
            return "exited"
        if any(isinstance(e, AppError) for e in safe_http.causes(exc)):
            return "runner"
        if self.auth_refused:
            return "auth"
        if any(isinstance(e, TimeoutError) for e in safe_http.causes(exc)):
            return "timeout"
        return "error"

    def close(self) -> None:
        """Blocking; safe on a client that never started or already stopped."""
        try:
            self.stop(None, None, None)
        except Exception:
            logger.warning("Could not close the MCP client for %s", self.server.name, exc_info=True)


def _detail(server: TurnServer, failed: ConnectFailed) -> str:
    if failed.cause == "exited":
        return server.local.stderr
    if failed.cause == "runner":
        # The runner's messages are its own fixed strings.
        return next(e.message for e in safe_http.causes(failed.__cause__) if isinstance(e, AppError))
    return ""


def _described(tool) -> dict:
    hints = tool.annotations.model_dump(by_alias=True, exclude_none=True) if tool.annotations else None
    return {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema, "annotations": hints}


async def list_on_loop(server: TurnServer) -> list[dict]:
    """Connects on the calling loop, lists the cleaned tools and disconnects. For the OAuth connect
    flow, which waits minutes for the user: a worker thread would be held all that time."""
    async with (
        _http(server.headers, server.auth) as http,
        streamable_http_client(server.url, http_client=http) as (read, write, *_),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        listed, cursor = [], None
        for _ in range(MAX_PAGES):
            page = await session.list_tools(params=PaginatedRequestParams(cursor=cursor) if cursor else None)
            listed.extend(page.tools)
            if (cursor := page.next_cursor) is None or len(listed) >= tools.MAX_TOOLS * 2:
                break
    return tools.clean(server.name, [_described(t) for t in listed])


async def list_tools(server: TurnServer) -> list[dict]:
    """Connects, lists the cleaned tools and disconnects. Raises ConnectFailed."""
    client = EchoClient(server)
    try:
        return await _connect(client)
    finally:
        await asyncio.to_thread(client.close)


# Clients still connecting when their turn was cancelled; each is closed once its connect returns.
_orphans: set[asyncio.Future] = set()


async def _connect(client: EchoClient) -> list[dict]:
    work = asyncio.ensure_future(asyncio.to_thread(client.connect))
    try:
        # Shielded: a worker thread cannot be cancelled, so a cancelled turn leaves it to finish.
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        _orphans.add(work)
        work.add_done_callback(lambda _: (_orphans.discard(work), asyncio.ensure_future(asyncio.to_thread(client.close))))
        raise


@dataclass
class TurnMcp:
    """One turn's MCP servers: started before the agent is built and stopped after it, however the
    turn ends. `changes` holds what the turn learned per server id, written back by the caller."""

    servers: list[TurnServer]
    user_id: str
    agent_id: str
    clients: list[EchoClient] = field(default_factory=list)
    unavailable: list[Unavailable] = field(default_factory=list)
    changes: dict[str, dict] = field(default_factory=dict)

    async def start(self) -> list[Unavailable]:
        ready = []
        for server in self.servers:
            if server.status == "ok":
                ready.append(server)
            else:
                self.unavailable.append(Unavailable(server.name, REASONS.get(server.status, REASONS["error"])))
        await asyncio.gather(*(self._start(server) for server in ready))
        self.clients.sort(key=lambda c: c.server.name)
        self.unavailable.sort(key=lambda u: u.name)
        return self.unavailable

    async def _start(self, server: TurnServer) -> None:
        client = EchoClient(server, self.user_id, self.agent_id)
        try:
            offered = await _connect(client)
        except ConnectFailed as failed:
            logger.warning("MCP server %s of user %s is unavailable (%s)", server.name, self.user_id, failed.cause, exc_info=failed.__cause__)
            self.unavailable.append(Unavailable(server.name, REASONS[failed.cause], _detail(server, failed)))
            self._learn(server)
            return
        digest = tools.digest(offered)
        if server.tools_hash is None:
            self._change(server, tools=offered, tools_hash=digest)
        elif digest != server.tools_hash:
            await asyncio.to_thread(client.close)
            self._change(server, pending_tools=offered, status="tools_changed")
            self.unavailable.append(Unavailable(server.name, REASONS["tools_changed"]))
            self._learn(server)
            return
        self.clients.append(client)

    def _change(self, server: TurnServer, **fields) -> None:
        self.changes.setdefault(server.id, {}).update(fields)

    def _learn(self, server: TurnServer) -> None:
        """What the server's OAuth provider learned: refreshed tokens, or that it must be connected again."""
        if server.auth is None:
            return
        if server.auth.store.changed:
            self._change(server, oauth=server.auth.store.blob)
        if server.auth.needs:
            self._change(server, status=server.auth.needs)

    def tool_info(self) -> dict[str, dict]:
        """Prefixed tool name to the server and the hints it claims, for the approval card."""
        return {f"{c.server.name}_{t['name']}": {"server": c.server.name, "hints": t["annotations"]} for c in self.clients for t in c.offered}

    async def stop(self) -> None:
        clients, self.clients = self.clients, []
        await asyncio.gather(*(asyncio.to_thread(c.close) for c in clients))
        for client in clients:
            self._learn(client.server)
