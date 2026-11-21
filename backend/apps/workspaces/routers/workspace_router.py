from fastapi import APIRouter, Query

from apps.workspaces.models.workspace import FileContent, GitFileStatus, GitFileVersions, SaveFile, Tree, Workspace, WorkspaceFile
from apps.workspaces.services import workspace_service as service
from core.config import get_settings

router = APIRouter(prefix="/api/workspaces")
PathQuery = Query(description="Path relative to the workspace root, such as src/app.py")


@router.post("", summary="Create a workspace", tags=["workspaces"])
async def create_workspace() -> Workspace:
    return await service.create_workspace(get_settings())


@router.get("", summary="List workspaces, newest first", tags=["workspaces"])
async def list_workspaces() -> list[Workspace]:
    return await service.list_workspaces(get_settings())


@router.get("/{workspace_id}/tree", summary="List the files in a workspace, without .git", tags=["workspaces"])
async def tree(workspace_id: str) -> Tree:
    return await service.tree(get_settings(), workspace_id)


@router.get("/{workspace_id}/file", summary="Read a file", tags=["workspaces"])
async def read_file(workspace_id: str, path: str = PathQuery) -> WorkspaceFile:
    content = await service.read_file(get_settings(), workspace_id, path)
    return WorkspaceFile(path=path, **content.model_dump())


@router.put("/{workspace_id}/file", summary="Save a text file, creating its folders", tags=["workspaces"])
async def write_file(workspace_id: str, body: SaveFile) -> WorkspaceFile:
    await service.write_file(get_settings(), workspace_id, body.path, body.content)
    return WorkspaceFile(path=body.path, content=body.content, encoding="utf-8")


@router.get("/{workspace_id}/git/status", summary="Changed files since the last commit", tags=["git"])
async def git_status(workspace_id: str) -> list[GitFileStatus]:
    return await service.git_status(get_settings(), workspace_id)


@router.get("/{workspace_id}/git/file", summary="A file's last committed and current versions, for a diff", tags=["git"])
async def git_file_versions(workspace_id: str, path: str = PathQuery) -> GitFileVersions:
    return await service.git_file_versions(get_settings(), workspace_id, path)
