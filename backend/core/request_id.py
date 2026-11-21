"""Give every request an id that is sent back to the caller and written on every log line made
while serving it, so a person can quote the id from an error message and the logs can be found."""

import logging
import re
import time
import uuid
from contextvars import ContextVar

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = "X-Request-ID"

# A caller may send its own id so one id follows a call across systems. It is logged and echoed,
# so only short ids of safe characters are accepted.
_INBOUND_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

_current: ContextVar[str | None] = ContextVar("request_id", default=None)

access_logger = logging.getLogger("access")


def current() -> str | None:
    """The id of the request being served, or None outside a request."""
    return _current.get()


def request_id(request: Request) -> str:
    # Read from the scope rather than the context variable: the catch-all error handler runs
    # outside this middleware, after the variable has been reset.
    return request.scope.get("state", {}).get("request_id", "")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        inbound = dict(scope.get("headers") or []).get(HEADER.lower().encode(), b"").decode("latin-1")
        rid = inbound if _INBOUND_ID.fullmatch(inbound) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid
        token = _current.set(rid)
        status = 500
        started = time.perf_counter()

        async def send_with_id(message: Message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((HEADER.lower().encode(), rid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            # The route template, not the raw path, so ids in paths do not make every line unique.
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            ms = round((time.perf_counter() - started) * 1000)
            access_logger.info("%s %s %s %sms", scope["method"], route, status, ms)
            _current.reset(token)
