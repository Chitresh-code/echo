"""Sends requests for a preview host, `<agent id>-<port>.<preview domain>`, to the preview handler
before anything else sees them, so a page the agent wrote is never served by, and can never reach,
the app's own routes."""

import re

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from apps.preview.services import preview_proxy


def preview_target(host: str, preview_url: str) -> tuple[str, int] | None | bool:
    """For a Host header: (agent id, port) for a preview host, False for any other host under the
    preview domain, None for a host outside it."""
    domain = preview_url.partition("://")[2].split(":")[0]
    name = host.lower().rsplit(":", 1)[0]
    if name != domain and not name.endswith(f".{domain}"):
        return None
    match = re.fullmatch(rf"([0-9a-f]{{32}})-([0-9]{{1,5}})\.{re.escape(domain)}", name)
    if not match or not 1 <= int(match[2]) <= 65535:
        return False
    return match[1], int(match[2])


class PreviewHostMiddleware:
    def __init__(self, app: ASGIApp, preview_url: str | None):
        self.app = app
        self.preview_url = preview_url

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if not self.preview_url or scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        host = dict(scope["headers"]).get(b"host", b"").decode("latin-1")
        target = preview_target(host, self.preview_url)
        if target is None:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            # shortcut: WebSockets are not forwarded, so dev servers' hot reload does not connect; add when the runner forwards upgrades.
            return await send({"type": "websocket.close", "code": 1008})
        if target is False:
            return await PlainTextResponse("There is no preview here.", 404)(scope, receive, send)
        await preview_proxy.serve(scope, receive, send, *target)
