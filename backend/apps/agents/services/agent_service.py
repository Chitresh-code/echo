"""Agent operations. An agent's files are its workspace, a git repository on the sandbox volume named
by the agent id. Every file operation runs through the runner, inside that workspace's jail, so a
path or symlink in it can never reach anything outside it."""

import asyncio
import base64
import logging
import re
import shlex
import shutil
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from strands.sandbox.errors import SandboxPathNotFoundError

from apps.agents.models.agent import (
    DEFAULT_NAME,
    MAX_FILE_BYTES,
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_FILES,
    Agent,
    AgentUpdate,
    FileContent,
    GitFileStatus,
    GitFileVersions,
    NewAgent,
    Process,
    Processes,
    ProcessLog,
    Tree,
    TreeEntry,
    Usage,
)
from apps.agents.repositories import agents
from apps.agents.services.git_status import parse_porcelain
from apps.agents.services.paths import check_agent_id, safe_relpath
from apps.chat.services import approvals, turn_service
from core.config import Settings
from core.errors import AppError
from sandbox import processes
from sandbox.runner_sandbox import RunnerSandbox, raise_for_runner_error, runner_client

logger = logging.getLogger(__name__)

MAX_TREE_ENTRIES = 5000
_TYPES = {"f": "file", "d": "dir", "l": "link"}
# Exit codes the commands below use to report a result, chosen to not clash with git or the shell.
_MISSING, _TOO_LARGE, _EXISTS = 77, 78, 79


def _sandbox(settings: Settings, agent_id: str) -> RunnerSandbox:
    return RunnerSandbox(check_agent_id(agent_id), settings.runner_socket, settings.command_timeout)


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


async def create_agent(settings: Settings, db: AsyncSession, owner_id: str, new: NewAgent) -> Agent:
    if await agents.count_for(db, owner_id) >= settings.max_agents:
        raise AppError(409, "agent_limit_reached", f"You have {settings.max_agents} workspaces, the most allowed. Delete one to start another.")
    agent_id = uuid.uuid4().hex
    # The runner first: a failed insert leaves an unused folder, never a row pointing at nothing.
    async with runner_client(settings.runner_socket) as client:
        await raise_for_runner_error(await client.post(f"/workspaces/{agent_id}"))
    agent = await agents.add(db, agent_id, owner_id, new.name or DEFAULT_NAME, new.job, new.approval_mode)
    await db.commit()
    return agent


async def list_agents(db: AsyncSession, owner_id: str) -> list[Agent]:
    return await agents.list_for(db, owner_id)


async def get_agent(db: AsyncSession, owner_id: str, agent_id: str) -> Agent:
    agent = await agents.get(db, agent_id, owner_id)
    if agent is None:
        raise _not_found()
    return agent


async def delete_agent(settings: Settings, db: AsyncSession, owner_id: str, agent_id: str) -> None:
    """Files first and the row last, so a failure part way leaves the agent listed and the delete
    can be repeated; every step skips what is already gone."""
    if turn_service.agent_busy(agent_id):
        raise AppError(409, "agent_busy", "This workspace has a turn in progress. Stop it or wait for it to end, then delete.")
    async with runner_client(settings.runner_socket) as client:
        response = await client.delete(f"/workspaces/{agent_id}")
        if response.status_code != 404:
            await raise_for_runner_error(response)
    for folder in ("sessions", "memory"):
        await asyncio.to_thread(shutil.rmtree, settings.data_dir / folder / check_agent_id(agent_id), ignore_errors=True)
    await agents.delete(db, agent_id, owner_id)
    await db.commit()


async def usage(settings: Settings, agent_id: str) -> Usage:
    async with runner_client(settings.runner_socket) as client:
        response = await client.get(f"/workspaces/{check_agent_id(agent_id)}/usage")
        await raise_for_runner_error(response)
    return Usage(**response.json()["data"])


async def list_processes(settings: Settings, agent_id: str) -> Processes:
    return Processes(**await processes.list_all(settings.runner_socket, check_agent_id(agent_id)))


async def process_logs(settings: Settings, agent_id: str, name: str, tail: int) -> ProcessLog:
    return ProcessLog(**await processes.logs(settings.runner_socket, check_agent_id(agent_id), name, tail))


async def stop_process(settings: Settings, agent_id: str, name: str) -> Process:
    return Process(**await processes.stop(settings.runner_socket, check_agent_id(agent_id), name))


async def update_agent(db: AsyncSession, owner_id: str, agent_id: str, change: AgentUpdate) -> Agent:
    fields = change.model_dump(exclude_none=True)
    if fields:
        await agents.update(db, agent_id, owner_id, fields)
        await db.commit()
    if change.approval_mode is not None:
        # Turns already running read it on their next call; switching to yolo lets a waiting call run.
        approvals.set_mode(agent_id, change.approval_mode)
    return await get_agent(db, owner_id, agent_id)


async def tree(settings: Settings, agent_id: str) -> Tree:
    sandbox = _sandbox(settings, agent_id)
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


async def read_file(settings: Settings, agent_id: str, path: str) -> FileContent:
    return await _read_working(_sandbox(settings, agent_id), safe_relpath(path))


def _path_exists(rel: str) -> AppError:
    return AppError(409, "path_exists", f"{rel} already exists. Pick another name.")


async def _check_space(settings: Settings, agent_id: str) -> None:
    # A full workspace's jail cannot write, and this says why instead of a bare failure.
    space = await usage(settings, agent_id)
    if space.used_bytes > space.limit_bytes:
        raise AppError(507, "disk_quota_exceeded", f"This agent uses all of its {space.limit_bytes // (1024 * 1024)} MB of storage. Delete files to save again.")


async def write_file(settings: Settings, agent_id: str, path: str, content: str, create: bool = False) -> None:
    data = content.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise _too_large()
    rel = safe_relpath(path)
    await _check_space(settings, agent_id)
    sandbox = _sandbox(settings, agent_id)
    if create:
        # noclobber makes the shell's create fail if anything has the name, in one step, so a file
        # another tab made a moment ago is never overwritten.
        target = shlex.quote(f"{sandbox.root}/{rel}")
        result = await sandbox.execute(f"mkdir -p -- \"$(dirname -- {target})\" || exit 1; [ -e {target} ] && exit {_EXISTS}; set -C; : > {target} || exit {_EXISTS}")
        if result.exit_code == _EXISTS:
            raise _path_exists(rel)
        if result.exit_code != 0:
            raise AppError(400, "write_failed", "The file could not be made. Check no file has the name of one of its folders.")
        if not data:
            return
    try:
        await sandbox.write_file(f"{sandbox.root}/{rel}", data)
    except OSError:
        raise AppError(400, "write_failed", "The file could not be saved. Check the path is not a directory.") from None


async def make_folder(settings: Settings, agent_id: str, path: str) -> None:
    rel = safe_relpath(path)
    await _check_space(settings, agent_id)
    sandbox = _sandbox(settings, agent_id)
    target = shlex.quote(f"{sandbox.root}/{rel}")
    result = await sandbox.execute(f"[ -e {target} ] && exit {_EXISTS}; mkdir -p -- {target}")
    if result.exit_code == _EXISTS:
        raise _path_exists(rel)
    if result.exit_code != 0:
        raise AppError(400, "write_failed", "The folder could not be made. Check no file has the name of one of its folders.")


def upload_target(folder: str, filename: str) -> str:
    """Where an uploaded file lands: its own name only, whatever path the browser sent, in `folder`."""
    name = re.split(r"[\\/]", filename or "")[-1]
    if name in ("", ".", "..") or "\0" in name:
        raise AppError(400, "invalid_path", f"{filename!r} is not a file name that can be saved.")
    return safe_relpath(f"{folder.strip('/')}/{name}" if folder.strip("/") else name)


async def upload(settings: Settings, agent_id: str, folder: str, files: list[tuple[str, bytes]], overwrite: bool) -> list[str]:
    if not files:
        raise AppError(400, "no_files", "Choose at least one file to upload.")
    if len(files) > MAX_UPLOAD_FILES:
        raise AppError(400, "too_many_files", f"Upload at most {MAX_UPLOAD_FILES} files at a time.")
    if sum(len(data) for _, data in files) > MAX_UPLOAD_BYTES:
        raise AppError(413, "upload_too_large", f"Upload at most {MAX_UPLOAD_BYTES // (1024 * 1024)} MB at a time.")
    for name, data in files:
        if len(data) > MAX_FILE_BYTES:
            raise AppError(413, "file_too_large", f"{name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    targets = [(upload_target(folder, name), data) for name, data in files]
    if len({t for t, _ in targets}) < len(targets):
        raise AppError(400, "duplicate_names", "Two of the files have the same name.")
    await _check_space(settings, agent_id)
    sandbox = _sandbox(settings, agent_id)
    if not overwrite:
        # One command for every name: prints the ones already there.
        tests = " ".join(f"[ -e {shlex.quote(f'{sandbox.root}/{t}')} ] && printf '%s\\0' {shlex.quote(t)};" for t, _ in targets)
        result = await sandbox.execute(f"{tests} true")
        if taken := [p for p in result.stdout.split("\0") if p]:
            raise AppError(409, "files_exist", f"{len(taken)} of these files already exist.", details={"paths": taken})
    written: list[str] = []
    for target, data in targets:
        try:
            await sandbox.write_file(f"{sandbox.root}/{target}", data)
        except OSError:
            raise AppError(400, "write_failed", f"{target} could not be saved. Check no folder has its name.", details={"written": written}) from None
        written.append(target)
    return written


async def git_status(settings: Settings, agent_id: str) -> list[GitFileStatus]:
    result = await _sandbox(settings, agent_id).execute("git status --porcelain=v1 -z --untracked-files=all")
    if result.exit_code != 0:
        raise _failed(result, "read its git status")
    return parse_porcelain(result.stdout)


async def git_file_versions(settings: Settings, agent_id: str, path: str) -> GitFileVersions:
    sandbox = _sandbox(settings, agent_id)
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


def _not_found() -> AppError:
    return AppError(404, "agent_not_found", "There is no workspace with this id.")


async def require_agent(db: AsyncSession, owner_id: str, agent_id: str) -> str:
    check_agent_id(agent_id)
    # Someone else's agent answers exactly like a missing one, so ids cannot be probed.
    if not await agents.owns(db, agent_id, owner_id):
        raise _not_found()
    return agent_id
