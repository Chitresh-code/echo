from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from apps.chat.routers.chat_router import router as chat_router
from apps.workspaces.routers.workspace_router import router as workspace_router
from core.error_handlers import register_error_handlers
from core.log_config import setup_logging
from core.request_id import RequestIdMiddleware
from core.responses import EnvelopeJSONResponse
from lifespan import lifespan

# The user guide, plain HTML kept at the repo root next to the backend. The image keeps the same layout.
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


class Health(BaseModel):
    status: str


def create_app() -> FastAPI:
    # /docs is the user guide, so the generated API reference lives under /api with everything else.
    app = FastAPI(
        title="Echo",
        version="0.1.0",
        lifespan=lifespan,
        default_response_class=EnvelopeJSONResponse,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    @app.get("/api/health", summary="Check the api is up", tags=["health"])
    def health() -> Health:
        return Health(status="ok")

    app.include_router(workspace_router)
    app.include_router(chat_router)

    app.mount("/docs", StaticFiles(directory=DOCS_DIR, html=True), name="docs")
    return app


setup_logging()
app = create_app()
