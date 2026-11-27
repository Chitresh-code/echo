from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.accounts.models.account import User
from apps.credentials.models.credential import Deleted
from apps.mcp.models.mcp_server import (
    McpServer,
    NewMcpServer,
    OAuthStart,
    SecretUpdate,
    ToolReview,
)
from apps.mcp.services import mcp_service as service
from apps.mcp.services import oauth
from core.auth import current_user
from core.config import get_settings
from core.db import db
from core.errors import AppError

# Every route needs a signed-in user, even one added later that forgets to ask for it.
router = APIRouter(prefix="/api/mcp-servers", tags=["mcp"], dependencies=[Depends(current_user)])
CurrentUser = Annotated[User, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(db)]


@router.post(
    "",
    summary="Add an MCP server",
    description="A remote server is reached over streamable HTTP at an https address, with no sign-in, fixed headers, or OAuth "
    "(connected afterwards). A local server is a command started inside each agent's workspace. Header and environment values "
    "are stored encrypted and never shown again; responses carry only their names.",
)
async def add_server(body: NewMcpServer, user: CurrentUser, session: Db) -> McpServer:
    return await service.add(get_settings(), session, user.id, body)


@router.get("", summary="List your MCP servers")
async def list_servers(user: CurrentUser, session: Db) -> list[McpServer]:
    return await service.list_servers(get_settings(), session, user.id)


@router.patch("/{server_id}", summary="Replace a server's headers or environment variables")
async def update_server(server_id: str, body: SecretUpdate, user: CurrentUser, session: Db) -> McpServer:
    return await service.update_secret(get_settings(), session, user.id, server_id, body)


@router.delete("/{server_id}", summary="Delete a server; agents that used it stop using it")
async def delete_server(server_id: str, user: CurrentUser, session: Db) -> Deleted:
    await service.delete(session, user.id, server_id)
    return Deleted(deleted=True)


@router.post(
    "/{server_id}/tools/review",
    summary="Accept a server's changed tools",
    description="A server whose tools changed since they were reviewed is left out of turns until its new tools are accepted here, by the `pending_hash` it lists.",
)
async def review_tools(server_id: str, body: ToolReview, user: CurrentUser, session: Db) -> McpServer:
    return await service.review_tools(get_settings(), session, user.id, server_id, body.hash)


@router.post(
    "/{server_id}/oauth",
    summary="Start connecting an OAuth server",
    description="Returns the provider's address to open in the browser. Once the user approves there, the provider sends them back to "
    "the callback, which stores the tokens and lists the server's tools. A started connection waits 10 minutes.",
)
async def start_oauth(server_id: str, user: CurrentUser, session: Db) -> OAuthStart:
    return OAuthStart(authorize_url=await service.start_oauth(get_settings(), session, user.id, server_id))


# Outside /api/mcp-servers: the callback is where providers send the user's browser back, and the
# client metadata document is fetched by authorization servers, so it is the one route with no session.
oauth_router = APIRouter(prefix="/api/mcp/oauth", tags=["mcp"])


@oauth_router.get(
    "/callback",
    summary="Where an OAuth provider returns after connecting a server",
    response_class=RedirectResponse,
    status_code=302,
    dependencies=[Depends(current_user)],
)
async def oauth_callback(
    user: CurrentUser, session: Db, state: str = "", code: str | None = None, iss: str | None = None, error: str | None = None
) -> RedirectResponse:
    # Always back to the page, which says what happened; never a bare error in the browser.
    try:
        server_id = await service.finish_oauth(get_settings(), session, user.id, state, code, iss, error)
    except AppError as failed:
        return RedirectResponse(f"/mcp?error={failed.code}", status_code=302)
    return RedirectResponse(f"/mcp?connected={server_id}", status_code=302)


@oauth_router.get("/client", summary="Echo's OAuth client metadata document")
async def client_document() -> JSONResponse:
    return JSONResponse(oauth.metadata_document(get_settings()), headers={"Cache-Control": "public, max-age=3600"})
