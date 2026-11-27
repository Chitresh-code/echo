"""Forwards an HTTP request from the api to a server listening inside a workspace's network
namespace, so the user can see a dev server the agent started.

The runner itself stays in the sandbox container's namespace. Each connection is opened by a new
thread that joins the workspace's namespace with setns, connects to its loopback and exits; the
socket keeps the namespace it was made in. A fresh thread every time matters: a pooled thread
would stay in that namespace and later work given to it would run there. The connection only ever
goes to loopback in the namespace the caller named, whatever host the request carries, so this
cannot be used to reach anything else."""

import asyncio
import os
import socket
import threading
from pathlib import Path

import anyio.abc
import httpcore
import httpx
from httpcore._backends.anyio import AnyIOStream
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import StreamingResponse

from app import jail, net

CONNECT_SECONDS = 10
TIMEOUT = httpx.Timeout(60.0, connect=CONNECT_SECONDS)

# Headers that describe one connection, not the message, so they are never passed on (RFC 9110 7.6.1).
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "proxy-connection", "te", "trailer", "transfer-encoding", "upgrade"}


def _connect_in(ns: Path, port: int) -> socket.socket:
    """Runs on its own thread: join the namespace, then connect to its loopback."""
    fd = os.open(ns, os.O_RDONLY)
    try:
        os.setns(fd, os.CLONE_NEWNET)
    finally:
        os.close(fd)
    error: OSError | None = None
    # Dev servers bind to 127.0.0.1, 0.0.0.0 or, when `localhost` resolves to it first, only ::1.
    for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_SECONDS)
        try:
            sock.connect((address, port))
            sock.setblocking(False)
            return sock
        except OSError as exc:
            sock.close()
            error = exc
    raise error


async def connect(ns: Path, port: int) -> socket.socket:
    loop = asyncio.get_running_loop()
    done: asyncio.Future = loop.create_future()

    def target():
        try:
            result = _connect_in(ns, port)
        except BaseException as exc:
            loop.call_soon_threadsafe(lambda e=exc: done.done() or done.set_exception(e))
        else:
            loop.call_soon_threadsafe(lambda: done.set_result(result) if not done.done() else result.close())

    threading.Thread(target=target, daemon=True, name="preview-connect").start()
    return await done


class _NamespaceBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, ns: Path, port: int):
        self._ns = ns
        self._port = port
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        # The host and port in the URL are ignored on purpose: the only place this connects is
        # the namespace's loopback on the port the route was given.
        try:
            sock = await connect(self._ns, self._port)
        except OSError as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        return AnyIOStream(await anyio.abc.SocketStream.from_socket(sock))

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("Unix sockets are not forwarded.")

    async def sleep(self, seconds):
        await self._inner.sleep(seconds)


def client(ns: Path, port: int) -> httpx.AsyncClient:
    """A client for one request. Connections are not reused, so nothing is shared between workspaces."""
    transport = httpx.AsyncHTTPTransport()
    # httpx has no public way to set httpcore's network backend; tests/test_preview.py checks
    # this attribute, so an httpx upgrade that moves it fails there.
    transport._pool._network_backend = _NamespaceBackend(ns, port)
    # No proxies from the environment and no redirects: a redirect is the browser's to follow.
    return httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False, timeout=TIMEOUT)


def end_to_end(raw: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    """Raw headers without the hop-by-hop ones, repeats (Set-Cookie) kept."""
    # Any header the Connection header names is hop-by-hop too.
    named = {h.strip().lower() for k, v in raw if k.lower() == b"connection" for h in v.decode("latin-1").split(",")}
    return [(k, v) for k, v in raw if k.decode("latin-1").lower() not in HOP_BY_HOP | named]


def upstream_target(raw_path: bytes, query: bytes) -> bytes:
    """The path and query to send upstream, as the browser sent them, from the raw route path
    /workspaces/<ws>/ports/<port>/http/<rest>. Taken raw so %2F and the like reach the server encoded."""
    parts = raw_path.split(b"/", 6)
    rest = b"/" + (parts[6] if len(parts) == 7 else b"")
    return rest + (b"?" + query if query else b"")


async def forward(settings: jail.Settings, workspace_id: str, port: int, request: Request) -> StreamingResponse:
    ns = net.path(settings, workspace_id)
    if not ns.exists():
        # Nothing has run since the namespace was made (or since a restart), so nothing listens.
        raise jail.JailError("no_network", "Nothing is running in this workspace.", 404)
    url = httpx.URL(scheme="http", host="localhost", port=port, raw_path=upstream_target(request.scope["raw_path"], request.scope["query_string"]))
    c = client(ns, port)
    # The Host header comes from the caller, which knows what the dev server expects.
    # A body only when the browser sent one: an empty chunked body on a GET is left unread by
    # simple servers, and closing with unread input resets the connection and cuts off the response.
    has_body = "content-length" in request.headers or "transfer-encoding" in request.headers
    upstream = c.build_request(request.method, url, headers=end_to_end(request.headers.raw), content=request.stream() if has_body else None)
    try:
        response = await c.send(upstream, stream=True)
    except httpx.TransportError as exc:
        await c.aclose()
        raise jail.JailError("upstream_unreachable", f"Nothing answered on port {port}.", 502) from exc

    async def close():
        await response.aclose()
        await c.aclose()

    # Raw bytes, still compressed if the server compressed them, so Content-Encoding stays true.
    forwarded = StreamingResponse(response.aiter_raw(), status_code=response.status_code, background=BackgroundTask(close))
    forwarded.raw_headers = end_to_end(response.headers.raw)
    return forwarded
