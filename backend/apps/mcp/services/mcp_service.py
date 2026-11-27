"""A user's MCP servers: adding, listing, changing their secrets, reviewing changed tools, and
choosing which agents use them. Secrets (headers, environment variables, OAuth clients and tokens)
are one encrypted JSON blob per server and only ever leave here decrypted for a turn."""

import json
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.credentials.services import crypto, safe_http
from apps.mcp.models.mcp_server import (
    AgentServers,
    McpServer,
    McpTool,
    NewMcpServer,
    SecretUpdate,
)
from apps.mcp.repositories import mcp_servers
from apps.mcp.services import connect, oauth, runner_stdio, tools
from core.config import Settings
from core.errors import AppError

logger = logging.getLogger(__name__)

# Each server is started for every turn of every agent that uses it, so both are kept small.
MAX_SERVERS = 20
MAX_PER_AGENT = 10
# The parts of a server's secret that an OAuth sign-in or refresh changes.
OAUTH_KEYS = ("client", "tokens", "expires_at", "scope", "discovered")


def _not_found() -> AppError:
    # Someone else's server answers exactly like a missing one, so ids cannot be probed.
    return AppError(404, "mcp_server_not_found", "There is no MCP server with this id.")


def _seal(settings: Settings, blob: dict) -> bytes | None:
    return crypto.encrypt(settings, json.dumps(blob)) if blob else None


def _open(settings: Settings, secret: bytes | None) -> dict:
    return json.loads(crypto.decrypt(settings, secret)) if secret else {}


def _plain(values) -> dict[str, str]:
    return {k: v.get_secret_value() for k, v in (values or {}).items()}


def _shown(settings: Settings, row: dict) -> McpServer:
    blob = _open(settings, row["secret"])
    pending = row["pending_tools"]

    def public(listed):
        return [McpTool(name=t["name"], description=t["description"], hints=t.get("annotations")) for t in listed]

    return McpServer(
        id=row["id"], name=row["name"], kind=row["kind"], url=row["url"], auth=row["auth"], command=row["command"], args=row["args"],
        header_names=sorted(blob.get("headers", {})), env_names=sorted(blob.get("env", {})), preregistered="preregistered" in blob,
        status=row["status"], tools=public(row["tools"] or []),
        pending_tools=public(pending) if pending is not None else None, pending_hash=tools.digest(pending) if pending is not None else None,
        created_at=row["created_at"],
    )


def check_url(url: str) -> str:
    try:
        safe_http.check_base_url(url)
    except AppError:
        raise AppError(400, "invalid_mcp_url", "An MCP server needs an https address with no user name, query or fragment, such as https://mcp.example.com/mcp.") from None
    # Kept as typed: unlike a model endpoint, a trailing slash can matter to an MCP server.
    return url


async def add(settings: Settings, db: AsyncSession, owner_id: str, new: NewMcpServer) -> McpServer:
    if await mcp_servers.count_for(db, owner_id) >= MAX_SERVERS:
        raise AppError(409, "mcp_server_limit_reached", f"You can have at most {MAX_SERVERS} MCP servers. Delete one you no longer use first.")
    if await mcp_servers.name_taken(db, owner_id, new.name):
        raise _name_taken(new.name)
    blob: dict = {}
    if new.kind == "remote":
        fields = {"url": check_url(new.url), "auth": new.auth, "command": None, "args": None}
        if new.headers:
            blob["headers"] = _plain(new.headers)
        if new.client_id:
            blob["preregistered"] = {"client_id": new.client_id}
            if new.client_secret:
                blob["preregistered"]["client_secret"] = new.client_secret.get_secret_value()
    else:
        fields = {"url": None, "auth": None, "command": new.command, "args": new.args or []}
        if new.env:
            blob["env"] = _plain(new.env)
    # A remote server is connected to now, and the tools the user sees in the reply count as
    # reviewed. An OAuth server cannot be used until the user connects it. A local server's first
    # turn lists its tools, and that list counts as reviewed, since the user just chose what to run.
    status, listed, digest = "ok", [], None
    if new.auth == "oauth":
        status = "needs_auth"
    elif new.kind == "remote":
        listed = await _check(connect.TurnServer("", new.name, fields["url"], "ok", blob.get("headers", {})))
        digest = tools.digest(listed)
    try:
        row = await mcp_servers.add(
            db, owner_id, name=new.name, kind=new.kind, secret=_seal(settings, blob), status=status, tools=listed, tools_hash=digest, **fields,
        )
        await db.commit()
    except IntegrityError:
        # Added at the same moment from another tab.
        raise _name_taken(new.name) from None
    return _shown(settings, row)


def _refused() -> AppError:
    return AppError(400, "endpoint_not_allowed", "The server, or an address it sent Echo to for signing in, is not https on the public internet. Echo connects only to those.")


def _unreachable() -> AppError:
    return AppError(502, "mcp_server_error", "Echo could not connect to the server and list its tools. Check the address and that the server is up, then try again.")


async def _check(server: connect.TurnServer) -> list[dict]:
    try:
        return await connect.list_tools(server)
    except connect.ConnectFailed as failed:
        if failed.cause == "refused":
            raise _refused() from None
        if failed.cause == "auth":
            raise AppError(400, "mcp_auth_failed", "The server refused the sign-in. Check the header names and values, then try again.") from None
        # The server's own error text can echo what was sent, so it stays in the log.
        logger.warning("Could not connect to MCP server %s (%s)", server.name, failed.cause, exc_info=failed.__cause__)
        raise _unreachable() from None


def _oauth_error(name: str, exc: BaseException) -> AppError:
    """What a failed connect flow tells the user; the details, which can hold another site's text, go to the log."""
    found = list(safe_http.causes(exc))
    if isinstance(exc, AppError):
        return exc
    if safe_http.refused(exc):
        return _refused()
    if any(isinstance(e, oauth.Unsupported) for e in found):
        return AppError(400, "oauth_unsupported", "The server's sign-in lacks protections Echo requires (PKCE with S256 over https), so Echo will not use it.")
    logger.warning("OAuth connect to MCP server %s failed", name, exc_info=exc)
    if any(isinstance(e, oauth.OAuthFlowError) for e in found):
        return AppError(400, "oauth_failed", "The sign-in did not complete. Start connecting again.")
    return _unreachable()


async def _oauth_row(db: AsyncSession, owner_id: str, server_id: str) -> dict:
    row = await _require(db, owner_id, server_id)
    if row["auth"] != "oauth":
        raise AppError(400, "not_oauth", "Only a server that signs in with OAuth is connected this way.")
    return row


async def start_oauth(settings: Settings, db: AsyncSession, owner_id: str, server_id: str) -> str:
    """Starts connecting an OAuth server and returns the provider's authorization URL."""
    row = await _oauth_row(db, owner_id, server_id)
    blob = _open(settings, row["secret"])
    # A fresh sign-in: the registered client is kept, the old tokens are not.
    blob.pop("tokens", None)
    blob.pop("expires_at", None)
    provider = oauth.Guarded(row["name"], row["url"], settings, blob)
    server = connect.TurnServer(row["id"], row["name"], row["url"], "ok", blob.get("headers", {}), auth=provider)
    try:
        return await oauth.start(owner_id, server_id, provider, lambda _: connect.list_on_loop(server))
    except Exception as exc:
        # Without metadata the SDK guesses /register, /authorize and /token on the server's own
        # host, which Echo will not use, so say what is actually missing.
        if provider.context.oauth_metadata is None and not isinstance(exc, AppError) and not safe_http.refused(exc):
            logger.warning("MCP server %s offers OAuth without metadata", row["name"], exc_info=exc)
            raise AppError(400, "oauth_no_metadata", "The server does not publish its sign-in details (OAuth metadata), so Echo cannot connect it with OAuth. If the provider gives you an API token, add the server with headers instead.") from None
        raise _oauth_error(row["name"], exc) from None


async def finish_oauth(settings: Settings, db: AsyncSession, owner_id: str, state: str, code: str | None, iss: str | None, error: str | None) -> str:
    """Completes a connect flow from the provider's redirect; returns the server id."""
    try:
        flow, listed = await oauth.finish(owner_id, state, code, iss, error)
    except Exception as exc:
        raise _oauth_error("(callback)", exc) from None
    row = await _require(db, owner_id, flow.server_id)
    # Headers or a client changed meanwhile are kept; the flow brings the tokens and its client.
    blob = {**_open(settings, row["secret"]), **{k: v for k, v in flow.provider.store.blob.items() if k in OAUTH_KEYS}}
    fields = {"secret": _seal(settings, blob), "status": "ok", "tools": listed, "tools_hash": tools.digest(listed), "pending_tools": None}
    await mcp_servers.update(db, row["id"], owner_id, **fields)
    await db.commit()
    return row["id"]


def _name_taken(name: str) -> AppError:
    return AppError(409, "mcp_server_name_taken", f"You already have an MCP server named {name}. Pick another name.")


async def list_servers(settings: Settings, db: AsyncSession, owner_id: str) -> list[McpServer]:
    return [_shown(settings, row) for row in await mcp_servers.list_for(db, owner_id)]


async def _require(db: AsyncSession, owner_id: str, server_id: str) -> dict:
    row = await mcp_servers.get(db, server_id, owner_id)
    if row is None:
        raise _not_found()
    return row


async def get_server(settings: Settings, db: AsyncSession, owner_id: str, server_id: str) -> McpServer:
    return _shown(settings, await _require(db, owner_id, server_id))


async def update_secret(settings: Settings, db: AsyncSession, owner_id: str, server_id: str, change: SecretUpdate) -> McpServer:
    row = await _require(db, owner_id, server_id)
    blob = _open(settings, row["secret"])
    if change.headers is not None:
        if row["auth"] != "headers":
            raise AppError(400, "secret_not_supported", "Only a remote server that signs in with headers takes headers.")
        blob["headers"] = _plain(change.headers)
        # New headers are tried before they replace the old ones; the tools are left to the next turn's check.
        await _check(connect.TurnServer(row["id"], row["name"], row["url"], "ok", blob["headers"]))
    else:
        if row["kind"] != "local":
            raise AppError(400, "secret_not_supported", "Only a local server takes environment variables.")
        blob["env"] = _plain(change.env)
        if not blob["env"]:
            del blob["env"]
    sealed = _seal(settings, blob)
    await mcp_servers.update(db, server_id, owner_id, secret=sealed)
    await db.commit()
    return _shown(settings, {**row, "secret": sealed})


async def review_tools(settings: Settings, db: AsyncSession, owner_id: str, server_id: str, accepted_hash: str) -> McpServer:
    """Accepts the changed tools a turn found, if they are still the ones the user looked at."""
    row = await _require(db, owner_id, server_id)
    pending = row["pending_tools"]
    if pending is None or tools.digest(pending) != accepted_hash:
        raise AppError(409, "tools_moved_on", "These tools are no longer the ones waiting for review. Reload the page to see the current list.")
    fields = {"tools": pending, "tools_hash": accepted_hash, "pending_tools": None, "status": "ok"}
    await mcp_servers.update(db, server_id, owner_id, **fields)
    await db.commit()
    return _shown(settings, {**row, **fields})


async def delete(db: AsyncSession, owner_id: str, server_id: str) -> None:
    # The agents' assignments go with it (ON DELETE CASCADE).
    if not await mcp_servers.delete(db, server_id, owner_id):
        raise _not_found()
    await db.commit()


async def get_for_agent(settings: Settings, db: AsyncSession, owner_id: str, agent_id: str) -> list[McpServer]:
    return [_shown(settings, row) for row in await mcp_servers.for_agent(db, agent_id, owner_id)]


async def set_for_agent(settings: Settings, db: AsyncSession, owner_id: str, agent_id: str, body: AgentServers) -> list[McpServer]:
    """The caller has checked the agent is the user's; every server must be too."""
    ids = list(dict.fromkeys(body.server_ids))
    if len(ids) > MAX_PER_AGENT:
        raise AppError(400, "too_many_mcp_servers", f"An agent can use at most {MAX_PER_AGENT} MCP servers.")
    for server_id in ids:
        await _require(db, owner_id, server_id)
    await mcp_servers.set_for_agent(db, agent_id, ids)
    await db.commit()
    return await get_for_agent(settings, db, owner_id, agent_id)


async def turn_servers(settings: Settings, db: AsyncSession, agent_id: str, owner_id: str) -> list[connect.TurnServer]:
    """The agent's servers with their secrets, for one turn. Local servers run in the agent's workspace."""
    servers = []
    for row in await mcp_servers.for_agent(db, agent_id, owner_id):
        blob = _open(settings, row["secret"])
        if row["kind"] == "local":
            local = runner_stdio.Local(agent_id, settings.runner_socket, row["command"], row["args"] or [], blob.get("env", {}))
            servers.append(connect.TurnServer(row["id"], row["name"], "", row["status"], tools_hash=row["tools_hash"], local=local))
            continue
        provider = oauth.Guarded(row["name"], row["url"], settings, blob) if row["auth"] == "oauth" else None
        servers.append(connect.TurnServer(row["id"], row["name"], row["url"], row["status"], blob.get("headers", {}), row["tools_hash"], provider))
    return servers


def save_changes(settings: Settings, owner_id: str, changes: dict[str, dict]):
    """A write for the turn's writer: what a turn learned about its servers (a first tool list,
    changed tools waiting for review, refreshed OAuth tokens, or that it must be connected again).
    A server deleted meanwhile matches no row.

    shortcut: a reconnect finished while the turn ran is overwritten by the turn's older tokens if
    the turn also refreshed them; rare, and the next turn's refresh or a reconnect fixes it."""

    async def write(db: AsyncSession) -> None:
        for server_id, fields in changes.items():
            fields = dict(fields)
            if "oauth" in fields:
                learned = fields.pop("oauth")
                row = await mcp_servers.get(db, server_id, owner_id)
                if row is None:
                    continue
                # Only the OAuth part comes from the turn; headers changed meanwhile are kept.
                fields["secret"] = _seal(settings, {**_open(settings, row["secret"]), **{k: learned[k] for k in OAUTH_KEYS if k in learned}})
            await mcp_servers.update(db, server_id, owner_id, **fields)

    return write
