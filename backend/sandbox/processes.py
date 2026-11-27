"""Long-running processes in an agent's workspace (dev servers, watchers), which the runner keeps
after the request that started them ends. The agent's tool and the user's routes both use these."""

import re
from pathlib import Path

from core.errors import AppError
from sandbox.runner_sandbox import raise_for_runner_error, runner_client


async def _call(socket_path: Path, method: str, path: str, **kwargs) -> dict:
    async with runner_client(socket_path) as client:
        response = await client.request(method, path, **kwargs)
        await raise_for_runner_error(response)
    return response.json()["data"]


# The runner's rule, checked here too because the name goes into the runner's path: its router
# decodes %2F before matching, so quoting alone would let a model-written name change the route.
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")


def _base(workspace_id: str, name: str | None = None) -> str:
    base = f"/workspaces/{workspace_id}/processes"
    if name is None:
        return base
    if not NAME.fullmatch(name):
        raise AppError(400, "invalid_process_name", "A process name is 1 to 32 lowercase letters, digits and dashes, starting with a letter or digit.")
    return f"{base}/{name}"


async def start(socket_path: Path, workspace_id: str, name: str, command: str, cwd: str | None = None) -> dict:
    _base(workspace_id, name)  # the same name check, though the name travels in the body
    return await _call(socket_path, "POST", _base(workspace_id), json={"name": name, "command": command, "cwd": cwd})


async def list_all(socket_path: Path, workspace_id: str) -> dict:
    """`{processes, ports}`: ports belong to the workspace, not to one process."""
    return await _call(socket_path, "GET", _base(workspace_id))


async def logs(socket_path: Path, workspace_id: str, name: str, tail: int = 200) -> dict:
    return await _call(socket_path, "GET", f"{_base(workspace_id, name)}/logs", params={"tail": tail})


async def stop(socket_path: Path, workspace_id: str, name: str) -> dict:
    return await _call(socket_path, "DELETE", _base(workspace_id, name))
