"""Terminals in an agent's workspace: an interactive shell the runner holds on a pseudo terminal,
which outlives the browser socket that watches it. The user's routes use these; the agent does not."""

import re
from pathlib import Path

from websockets.asyncio.client import ClientConnection, unix_connect

from core.errors import AppError
from sandbox.processes import _call

ID = re.compile(r"[0-9a-f]{32}")


def check_id(terminal_id: str) -> str:
    # Checked here because the id goes into the runner's path.
    if not ID.fullmatch(terminal_id):
        raise AppError(404, "terminal_not_found", "This terminal has ended. Open a new one.")
    return terminal_id


async def start(socket_path: Path, workspace_id: str, cols: int, rows: int) -> dict:
    return await _call(socket_path, "POST", f"/workspaces/{workspace_id}/terminals", json={"cols": cols, "rows": rows})


async def list_all(socket_path: Path, workspace_id: str) -> list[dict]:
    return (await _call(socket_path, "GET", f"/workspaces/{workspace_id}/terminals"))["terminals"]


async def stop(socket_path: Path, workspace_id: str, terminal_id: str) -> None:
    await _call(socket_path, "DELETE", f"/workspaces/{workspace_id}/terminals/{check_id(terminal_id)}")


def connect(socket_path: Path, workspace_id: str, terminal_id: str) -> ClientConnection:
    """The runner's socket for one terminal, as an async context manager. Pings are left to the
    browser's side: a socket on the same host does not go quiet behind a proxy."""
    return unix_connect(
        str(socket_path), f"ws://runner/workspaces/{workspace_id}/terminals/{check_id(terminal_id)}",
        ping_interval=None, max_size=1024 * 1024, open_timeout=10,
    )
