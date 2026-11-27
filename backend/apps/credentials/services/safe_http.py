"""The HTTP client for custom endpoints, which are addresses users type. The api holds every user's
keys and sits next to the runner's socket, so it must not be usable to reach loopback, the private
network or cloud metadata (SSRF).

The check happens when a connection opens: the host is resolved once, every address it resolves to
must be public, and the connection goes to an address that was checked. Checking a URL up front and
connecting later would let a DNS answer change in between. TLS still uses the host name for SNI and
the certificate check, since httpcore passes the original host to start_tls.

`client()` is on httpx, which the model SDKs take; `client2()` is the same guard on httpx2, which the
MCP SDK takes. Both share the address check."""

import ipaddress
import socket
from urllib.parse import urlsplit

import anyio
import httpcore
import httpcore2
import httpx
import httpx2

from core.errors import AppError

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class EndpointNotAllowed(Exception):
    """The endpoint's host resolves to an address Echo refuses to call."""


# shortcut: no internal address is ever allowed, so self-hosted models (Ollama, a LAN server) cannot be used; add an operator allowlist if someone needs one.
def _allowed(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    # A mapped address is an IPv4 address in IPv6 clothing; refuse it rather than reason about it.
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return False
    # is_global is false for loopback, private, link-local (cloud metadata), carrier-grade NAT,
    # reserved, unspecified and documentation ranges.
    return ip.is_global and not ip.is_multicast


async def _getaddrinfo(host: str, port: int) -> list[str]:
    return [info[4][0] for info in await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def _checked_backend(core):
    """The guarded network backend for `core`, httpcore or httpcore2, whose interfaces match."""

    class CheckedBackend(core.AsyncNetworkBackend):
        def __init__(self):
            self._inner = core.AnyIOBackend()

        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            addresses = await _getaddrinfo(host, port)
            # Every address, not just the first: otherwise a host with one public and one private
            # address could be retried until the private one is used.
            if not addresses or not all(_allowed(a) for a in addresses):
                raise EndpointNotAllowed(host)
            return await self._inner.connect_tcp(addresses[0], port, timeout, local_address, socket_options)

        async def connect_unix_socket(self, path, timeout=None, socket_options=None):
            raise EndpointNotAllowed(path)

        async def sleep(self, seconds):
            await self._inner.sleep(seconds)

    return CheckedBackend


_CheckedBackend = _checked_backend(httpcore)
_CheckedBackend2 = _checked_backend(httpcore2)


def client() -> httpx.AsyncClient:
    """A new client per use: httpx connections cannot be shared across event loops."""
    transport = httpx.AsyncHTTPTransport()
    # httpx has no public way to set httpcore's network backend; tests/credentials/test_safe_http.py
    # connects through this client, so an httpx upgrade that moves the attribute fails there.
    transport._pool._network_backend = _CheckedBackend()
    # No proxies from the environment, which would connect for us unchecked, and no redirects,
    # which would only be checked again by luck of going through the same backend.
    return httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False, timeout=TIMEOUT)


# MCP servers stream results, so a read can wait as long as a slow tool takes.
TIMEOUT2 = httpx2.Timeout(30.0, read=300.0)


def client2(headers: dict[str, str] | None = None, auth=None) -> httpx2.AsyncClient:
    """The same guard on httpx2, for the MCP SDK. A new client per connection, since each MCP
    client runs on its own thread and loop. `auth` is an httpx2 auth flow, such as OAuth."""
    transport = httpx2.AsyncHTTPTransport()
    # As in client(): tests/credentials/test_safe_http.py connects through it, so a move fails there.
    transport._pool._network_backend = _CheckedBackend2()
    return httpx2.AsyncClient(transport=transport, trust_env=False, follow_redirects=False, timeout=TIMEOUT2, headers=headers, auth=auth)


def check_base_url(url: str | None) -> str:
    """An https address with a host and nothing that could smuggle in credentials or change the path."""
    parts = urlsplit(url or "")
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise AppError(400, "invalid_base_url", "A custom endpoint needs an https address with no user name, query or fragment, such as https://api.example.com/v1.")
    return url.rstrip("/")


def causes(exc: BaseException):
    """Every error behind `exc`: its cause chain and, since anyio task groups in the MCP SDK wrap
    errors, the members of any exception group on the way."""
    seen: set[int] = set()
    todo = [exc]
    while todo and len(seen) < 100:  # a bound, in case a chain loops back on itself
        exc = todo.pop()
        if exc is None or id(exc) in seen:
            continue
        seen.add(id(exc))
        yield exc
        if isinstance(exc, BaseExceptionGroup):
            todo.extend(exc.exceptions)
        todo.append(exc.__cause__ or exc.__context__)


def refused(exc: BaseException) -> bool:
    """Whether an error from a provider SDK was caused by a refused address, however it was wrapped."""
    return any(isinstance(e, EndpointNotAllowed) for e in causes(exc))
