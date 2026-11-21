"""Workspace operations. Every one runs through the runner, inside the workspace's jail, so a path
or symlink in a workspace can never reach anything outside it."""

import base64
import logging
import shlex
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from strands.sandbox.errors import SandboxPathNotFoundError

from apps.workspaces.models.workspace import (
    MAX_FILE_BYTES,
    FileContent,
    GitFileStatus,
    GitFileVersions,
    Tree,
    TreeEntry,
    Workspace,
)
from apps.workspaces.repositories import workspaces
from apps.workspaces.services.git_status import parse_porcelain
from apps.workspaces.services.paths import check_workspace_id, safe_relpath
from core.config import Settings
from core.errors import AppError
from sandbox.runner_sandbox import RunnerSandbox, raise_for_runner_error, runner_client

logger = logging.getLogger(__name__)

MAX_TREE_ENTRIES = 5000
_TYPES = {"f": "file", "d": "dir", "l": "link"}
# Exit codes the commands below use to report a result, chosen to not clash with git or the shell.
_MISSING, _TOO_LARGE = 77, 78


def _sandbox(settings: Settings, workspace_id: str) -> RunnerSandbox:
    return RunnerSandbox(check_workspace_id(workspace_id), settings.runner_socket, settings.command_timeout)


def _content(data: bytes) -> FileContent:
    try:
        return FileContent(content=data.decode("utf-8"), encoding="utf-8")
    except UnicodeDecodeError:
        return FileContent(content=base64.b64encode(data).decode("ascii"), encoding="base64")


def _too_large() -> AppError:
    return AppError(413, "file_too_large", f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")


def _failed(result, what: str) -> AppError:
    # The command's stderr can hold the user's file contents, so it goes to the log, not the caller.
    logger.warning("Workspace command to %s exited %s: %s", what, result.exit_code, result.stderr[-2000:])
    return AppError(500, "command_failed", f"The workspace could not {what}.")


async def create_workspace(settings: Settings, db: AsyncSession, owner_id: str) -> Workspace:
    workspace_id = uuid.uuid4().hex
    # The runner first: a failed insert leaves an unused folder, never a row pointing at nothing.
    async with runner_client(settings.runner_socket) as client:
        await raise_for_runner_error(await client.post(f"/workspaces/{workspace_id}"))
    await workspaces.add(db, workspace_id, owner_id)
    await db.commit()
    return Workspace(id=workspace_id)


async def list_workspaces(db: AsyncSession, owner_id: str) -> list[Workspace]:
    return [Workspace(id=i) for i in await workspaces.list_for(db, owner_id)]


async def tree(settings: Settings, workspace_id: str) -> Tree:
    sandbox = _sandbox(settings, workspace_id)
    # One more than the cap, so a full tree can be told apart from a cut one.
    result = await sandbox.execute(
        f"find . -mindepth 1 -path ./.git -prune -o -printf '%y %P\\0' | head -z -n {MAX_TREE_ENTRIES + 1}"
    )
    if result.exit_code != 0:
        raise _failed(result, "list its files")
    fields = [f for f in result.stdout.split("\0") if f]
    entries = [TreeEntry(path=f[2:], type=_TYPES.get(f[0], "other")) for f in fields[:MAX_TREE_ENTRIES]]
    return Tree(entries=entries, truncated=len(fields) > MAX_TREE_ENTRIES)


async def _read_working(sandbox: RunnerSandbox, rel: str, missing_ok: bool = False) -> FileContent | None:
    path = f"{sandbox.root}/{rel}"
    size = await sandbox.execute(f"stat -L -c %s -- {shlex.quote(path)}")
    if size.exit_code == 0 and int(size.stdout.strip() or 0) > MAX_FILE_BYTES:
        raise _too_large()
    try:
        return _content(await sandbox.read_file(path))
    except SandboxPathNotFoundError:
        if missing_ok:
            return None
        raise AppError(404, "file_not_found", "There is no file at this path.") from None
    except IsADirectoryError:
        raise AppError(400, "is_a_directory", "The path is a directory, not a file.") from None
    except PermissionError:
        raise AppError(403, "permission_denied", "The file cannot be read.") from None


async def read_file(settings: Settings, workspace_id: str, path: str) -> FileContent:
    return await _read_working(_sandbox(settings, workspace_id), safe_relpath(path))


async def write_file(settings: Settings, workspace_id: str, path: str, content: str) -> None:
    data = content.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise _too_large()
    sandbox = _sandbox(settings, workspace_id)
    rel = safe_relpath(path)
    try:
        await sandbox.write_file(f"{sandbox.root}/{rel}", data)
    except OSError:
        raise AppError(400, "write_failed", "The file could not be saved. Check the path is not a directory.") from None


async def git_status(settings: Settings, workspace_id: str) -> list[GitFileStatus]:
    result = await _sandbox(settings, workspace_id).execute("git status --porcelain=v1 -z --untracked-files=all")
    if result.exit_code != 0:
        raise _failed(result, "read its git status")
    return parse_porcelain(result.stdout)


async def git_file_versions(settings: Settings, workspace_id: str, path: str) -> GitFileVersions:
    sandbox = _sandbox(settings, workspace_id)
    rel = safe_relpath(path)
    obj = shlex.quote(f"HEAD:{rel}")
    # base64 so binary content survives the text stream.
    result = await sandbox.execute(
        f"s=$(git cat-file -s {obj} 2>/dev/null) || exit {_MISSING}; "
        f"[ \"$s\" -le {MAX_FILE_BYTES} ] || exit {_TOO_LARGE}; git cat-file blob {obj} | base64"
    )
    if result.exit_code == _TOO_LARGE:
        raise _too_large()
    if result.exit_code not in (0, _MISSING):
        raise _failed(result, "read the last commit")
    head = _content(base64.b64decode("".join(result.stdout.split()))) if result.exit_code == 0 else None
    return GitFileVersions(head=head, working=await _read_working(sandbox, rel, missing_ok=True))


async def require_workspace(db: AsyncSession, owner_id: str, workspace_id: str) -> str:
    check_workspace_id(workspace_id)
    # Someone else's workspace answers exactly like a missing one, so ids cannot be probed.
    if not await workspaces.owns(db, workspace_id, owner_id):
        raise AppError(404, "workspace_not_found", "There is no workspace with this id.")
    return workspace_id
