"""Serves a preview host: checks the browser may see this agent's port, then passes the request to
the runner, which forwards it to the server listening in the agent's workspace.

What comes back is a page the agent wrote, so it is treated like any other site: it only ever runs
on its own host, it never sees the preview cookie, and only Echo may frame it."""

import html
import json

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, StreamingResponse
from starlette.types import Receive, Scope, Send

from apps.agents.repositories import agents
from apps.preview.services.preview_service import COOKIE, COOKIE_SECONDS, START_PATH, cookie_value, user_for
from core.config import get_settings
from sandbox.runner_sandbox import runner_client

MAX_BODY = 10 * 1024 * 1024

# Headers that describe one connection, not the message (RFC 9110 7.6.1). Host is set here instead.
_DROP = {b"connection", b"keep-alive", b"proxy-authenticate", b"proxy-authorization", b"proxy-connection", b"te", b"trailer", b"transfer-encoding", b"upgrade", b"host"}


class _TooLarge(Exception):
    pass


def _page(status: int, message: str) -> HTMLResponse:
    body = f"<!doctype html><meta charset=utf-8><title>Echo preview</title><p>{html.escape(message)}</p>"
    return HTMLResponse(body, status, headers={"Cache-Control": "no-store"})


async def _owns(scope: Scope, agent_id: str, user_id: str) -> bool:
    # Checked on every request, so a deleted agent or one that changed hands stops showing at once.
    async with async_sessionmaker(scope["app"].state.db_engine)() as session:
        return await agents.owns(session, agent_id, user_id)


def _is_ours(cookie: bytes) -> bool:
    return cookie.split(b"=", 1)[0].strip() == COOKIE.encode()


def _request_headers(raw: list[tuple[bytes, bytes]], port: int) -> list[tuple[bytes, bytes]]:
    named = {h.strip().lower().encode() for k, v in raw if k == b"connection" for h in v.decode("latin-1").split(",")}
    out = []
    for key, value in raw:
        if key in _DROP or key in named:
            continue
        if key == b"cookie":
            # The preview cookie is Echo's, not the agent's server's.
            value = b"; ".join(p.strip() for p in value.split(b";") if p.strip() and not _is_ours(p))
            if not value:
                continue
        out.append((key, value))
    # Dev servers that check Host (Vite does) accept their own localhost address.
    out.append((b"host", f"localhost:{port}".encode()))
    return out


def _response_headers(raw: list[tuple[bytes, bytes]], public_url: str) -> list[tuple[bytes, bytes]]:
    out = [(k, v) for k, v in raw if k.lower() not in _DROP and not (k.lower() == b"set-cookie" and _is_ours(v))]
    # A second policy is enforced alongside any the server sets, so its own cannot loosen this one.
    out.append((b"content-security-policy", f"frame-ancestors {public_url}".encode()))
    return out


# The runner's own refusals, as opposed to whatever the agent's server answers.
_RUNNER_CODES = {"no_network", "upstream_unreachable"}


async def _runner_error(response: httpx.Response) -> str | None:
    """The runner's message when it, not the agent's server, answered: shown as a page instead of
    JSON. A server that answers the same way only changes how its own error looks."""
    if response.status_code not in (404, 502) or "content-encoding" in response.headers or not response.headers.get("content-type", "").startswith("application/json"):
        return None
    if int(response.headers.get("content-length") or 1 << 20) > 1024:
        return None
    try:
        error = json.loads(await response.aread())["error"]
    except (ValueError, KeyError, TypeError):
        return None
    return error.get("message") if isinstance(error, dict) and error.get("code") in _RUNNER_CODES else None


async def serve(scope: Scope, receive: Receive, send: Send, agent_id: str, port: int) -> None:
    settings = get_settings()
    request = Request(scope, receive)

    if scope["path"] == START_PATH:
        user_id = user_for(settings, "start", request.query_params.get("token"), agent_id, port)
        if user_id is None or not await _owns(scope, agent_id, user_id):
            return await _page(403, "This preview link is not valid any more. Open the preview from Echo.")(scope, receive, send)
        response = RedirectResponse("/", 303, headers={"Cache-Control": "no-store"})
        # SameSite=None and Partitioned so the cookie works inside Echo's frame; host-only, so no
        # other preview host gets it.
        response.headers.append("set-cookie", f"{COOKIE}={cookie_value(settings, user_id, agent_id, port)}; Max-Age={COOKIE_SECONDS}; Path=/; HttpOnly; Secure; SameSite=None; Partitioned")
        return await response(scope, receive, send)

    user_id = user_for(settings, "cookie", request.cookies.get(COOKIE), agent_id, port)
    if user_id is None or not await _owns(scope, agent_id, user_id):
        return await _page(403, "Open this preview from Echo.")(scope, receive, send)

    headers = request.headers
    if int(headers.get("content-length") or 0) > MAX_BODY:
        return await _page(413, "The request is too large to preview.")(scope, receive, send)

    async def body():
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY:
                raise _TooLarge
            yield chunk

    # The raw path and query, so %2F and the like reach the server as the browser sent them.
    target = f"/workspaces/{agent_id}/ports/{port}/http".encode() + (scope.get("raw_path") or scope["path"].encode())
    if scope["query_string"]:
        target += b"?" + scope["query_string"]
    has_body = "content-length" in headers or "transfer-encoding" in headers
    client = runner_client(settings.runner_socket)
    upstream = client.build_request(
        scope["method"], httpx.URL(scheme="http", host="runner", raw_path=target),
        headers=_request_headers(scope["headers"], port), content=body() if has_body else None,
    )
    try:
        response = await client.send(upstream, stream=True)
    except _TooLarge:
        await client.aclose()
        return await _page(413, "The request is too large to preview.")(scope, receive, send)
    except httpx.TransportError:
        await client.aclose()
        return await _page(502, "Echo could not reach the workspace.")(scope, receive, send)

    async def close():
        await response.aclose()
        await client.aclose()

    message = await _runner_error(response)
    if message:
        await close()
        return await _page(response.status_code, message)(scope, receive, send)

    async def read_already():
        yield response.content

    # Unencoded when it was read above, so the bytes read are the raw ones.
    forwarded = StreamingResponse(read_already() if response.is_stream_consumed else response.aiter_raw(), status_code=response.status_code, background=BackgroundTask(close))
    forwarded.raw_headers = _response_headers(response.headers.raw, settings.public_url)
    await forwarded(scope, receive, send)
