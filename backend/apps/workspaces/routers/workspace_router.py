from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.accounts.models.account import User
from apps.workspaces.models.workspace import FileContent, GitFileStatus, GitFileVersions, SaveFile, Tree, Workspace, WorkspaceFile
from apps.workspaces.services import workspace_service as service
from core.auth import current_user
from core.config import get_settings
from core.db import db

# Every route needs a signed-in user, even one added later that forgets to ask for it.
router = APIRouter(prefix="/api/workspaces", dependencies=[Depends(current_user)])
PathQuery = Query(description="Path relative to the workspace root, such as src/app.py")
CurrentUser = Annotated[User, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(db)]


async def owned_workspace(workspace_id: str, user: CurrentUser, session: Db) -> str:
    """The path's workspace id, once it is known to belong to the signed-in user."""
    return await service.require_workspace(session, user.id, workspace_id)


OwnedWorkspace = Annotated[str, Depends(owned_workspace)]


@router.post("", summary="Create a workspace", tags=["workspaces"])
async def create_workspace(user: CurrentUser, session: Db) -> Workspace:
    return await service.create_workspace(get_settings(), session, user.id)


@router.get("", summary="List workspaces, newest first", tags=["workspaces"])
async def list_workspaces(user: CurrentUser, session: Db) -> list[Workspace]:
    return await service.list_workspaces(session, user.id)


@router.get("/{workspace_id}/tree", summary="List the files in a workspace, without .git", tags=["workspaces"])
async def tree(workspace_id: OwnedWorkspace) -> Tree:
    return await service.tree(get_settings(), workspace_id)


@router.get("/{workspace_id}/file", summary="Read a file", tags=["workspaces"])
async def read_file(workspace_id: OwnedWorkspace, path: str = PathQuery) -> WorkspaceFile:
    content = await service.read_file(get_settings(), workspace_id, path)
    return WorkspaceFile(path=path, **content.model_dump())


@router.put("/{workspace_id}/file", summary="Save a text file, creating its folders", tags=["workspaces"])
async def write_file(workspace_id: OwnedWorkspace, body: SaveFile) -> WorkspaceFile:
    await service.write_file(get_settings(), workspace_id, body.path, body.content)
    return WorkspaceFile(path=body.path, content=body.content, encoding="utf-8")


@router.get("/{workspace_id}/git/status", summary="Changed files since the last commit", tags=["git"])
async def git_status(workspace_id: OwnedWorkspace) -> list[GitFileStatus]:
    return await service.git_status(get_settings(), workspace_id)


@router.get("/{workspace_id}/git/file", summary="A file's last committed and current versions, for a diff", tags=["git"])
async def git_file_versions(workspace_id: OwnedWorkspace, path: str = PathQuery) -> GitFileVersions:
    return await service.git_file_versions(get_settings(), workspace_id, path)
