from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

from apps.accounts.routers.auth_router import router as auth_router
from apps.accounts.services.oidc import state_cookie_key
from apps.agents.routers.agent_router import router as agent_router
from apps.chat.routers.chat_router import router as chat_router
from apps.credentials.routers.credential_router import router as credential_router
from apps.preview.routers.preview_router import router as preview_router
from apps.terminal.routers.terminal_router import router as terminal_router, socket_router as terminal_socket_router
from core.auth import check_origin
from core.config import get_settings
from core.error_handlers import register_error_handlers
from core.log_config import setup_logging
from core.request_id import RequestIdMiddleware
from core.preview_host import PreviewHostMiddleware
from core.web_app import WebHeadersMiddleware, csp, serve_web_app
from core.responses import EnvelopeJSONResponse
from lifespan import lifespan

# The user guide, plain HTML kept at the repo root next to the backend, and the built browser app.
# The image keeps the same layout.
REPO_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_DIR / "docs"
WEB_DIR = REPO_DIR / "web" / "dist"


class Health(BaseModel):
    status: str


def create_app(web_dir: Path | None = None) -> FastAPI:
    # /docs is the user guide, so the generated API reference lives under /api with everything else.
    app = FastAPI(
        title="Echo",
        version="0.1.0",
        lifespan=lifespan,
        default_response_class=EnvelopeJSONResponse,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
        dependencies=[Depends(check_origin)],
    )
    settings = get_settings()
    # Holds only the sign-in state (state, nonce and PKCE verifier) for the ten minutes a sign-in may
    # take. Who is signed in lives in the echo_session cookie, not here.
    app.add_middleware(
        SessionMiddleware, secret_key=state_cookie_key(settings), session_cookie="echo_signin", max_age=600,
        path="/api/auth", same_site="lax", https_only=settings.public_url.startswith("https://"),
    )
    app.add_middleware(WebHeadersMiddleware, csp=csp(settings.preview_url))
    # Outside the app's own headers and inside the request id: a preview host is answered here
    # and never reaches a route, the sign-in session or the app's CSP.
    app.add_middleware(PreviewHostMiddleware, preview_url=settings.preview_url)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    @app.get("/api/health", summary="Check the api is up", tags=["health"])
    def health() -> Health:
        return Health(status="ok")

    app.include_router(auth_router)
    app.include_router(credential_router)
    app.include_router(agent_router)
    app.include_router(chat_router)
    app.include_router(preview_router)
    app.include_router(terminal_router)
    app.include_router(terminal_socket_router)

    # The mount only matches /docs/..., so without this a bare /docs would reach the web app's
    # catch-all and show the app instead of the guide.
    @app.get("/docs", include_in_schema=False)
    def guide_root() -> RedirectResponse:
        return RedirectResponse("/docs/")

    app.mount("/docs", StaticFiles(directory=DOCS_DIR, html=True), name="docs")
    serve_web_app(app, web_dir or WEB_DIR)
    return app


setup_logging()
app = create_app()
