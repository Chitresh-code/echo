"""Serves the browser app, the built React files in web/dist, from the same origin as the API, so
the session cookie and the Origin check work without CORS."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Scripts only from Echo itself. Agent output reaches the page, so images are limited to Echo and
# data: URLs: a remote image in a reply would otherwise send data to whoever hosts it. Inline
# styles are allowed because the component library injects its styles at runtime; Monaco runs its
# workers from blob: URLs. Frames only from the preview domain, where the agents' dev servers show.
def csp(preview_url: str | None) -> str:
    scheme, _, domain = preview_url.partition("://") if preview_url else ("", "", "")
    frames = f"{scheme}://*.{domain}" if preview_url else "'none'"
    return (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
        f"img-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; frame-src {frames}; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


class WebHeadersMiddleware:
    """Security headers on everything outside /api. /api is left alone because the generated API
    reference there loads its scripts from a CDN."""

    def __init__(self, app: ASGIApp, csp: str):
        self.app = app
        self.csp = csp

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or _is_api(scope["path"]):
            return await self.app(scope, receive, send)

        async def send_with_headers(message: Message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = self.csp
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "same-origin"
                # Built asset names carry a content hash, so a cached copy is never stale.
                if scope["path"].startswith("/assets/") and message["status"] == 200:
                    headers["Cache-Control"] = "public, max-age=31536000, immutable"
                # Guide files keep their names across releases, so the browser must check each time
                # (a cheap ETag round trip) or it shows a new page with an old stylesheet.
                elif scope["path"].startswith("/docs/"):
                    headers["Cache-Control"] = "no-cache"
            await send(message)

        await self.app(scope, receive, send_with_headers)


def serve_web_app(app: FastAPI, web_dir: Path) -> None:
    """Register the app's files and a fallback that answers every other page path with index.html,
    so a link such as /agents/<id> loads the app, which then routes in the browser. Call it after
    every other route. Without a build (backend-only development) nothing is registered."""
    index = web_dir / "index.html"
    if not index.is_file():
        return
    if (web_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=web_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def web_app(path: str) -> FileResponse:
        # Unknown API paths keep their JSON 404 instead of getting the app's page.
        if _is_api(f"/{path}"):
            raise StarletteHTTPException(404)
        # no-cache so a deploy's new index.html, which names the new asset files, is picked up.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
