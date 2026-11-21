"""The Strands sandbox for a workspace: every command goes to the runner in the sandbox container,
which starts it in that workspace's jail. The api never touches workspace files itself."""

import json
import math
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
from strands.sandbox import ExecutionResult, PosixShellSandbox, StreamChunk
from strands.sandbox.errors import SandboxTimeoutError
from strands.sandbox.posix_shell import validate_env_keys

from core.errors import AppError

# Where workspaces live in the sandbox container. A jail sees its workspace at this same path, so a
# path the api sends means the same thing inside the jail.
WORKSPACES_ROOT = "/data/workspaces"

# Commands can run for many minutes with no output, so only connecting has a limit; the runner
# enforces the command's own time limit.
_TIMEOUT = httpx.Timeout(None, connect=5.0)


def runner_client(socket_path: Path) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket_path)), base_url="http://runner", timeout=_TIMEOUT)


async def raise_for_runner_error(response: httpx.Response) -> None:
    """Turn a runner error envelope into an AppError with the same status and code. The runner's
    messages are its own fixed strings, so they are safe to show."""
    if response.is_success:
        return
    await response.aread()
    try:
        error = response.json()["error"]
        code, message = error["code"], error["message"]
    except (ValueError, KeyError, TypeError):
        code, message = "runner_error", "The runner failed."
    raise AppError(response.status_code, code, message)


class RunnerSandbox(PosixShellSandbox):
    def __init__(self, workspace_id: str, socket_path: Path, default_timeout: int):
        self.workspace_id = workspace_id
        self.root = f"{WORKSPACES_ROOT}/{workspace_id}"
        self.socket_path = socket_path
        self.default_timeout = default_timeout

    async def execute_streaming(
        self,
        command: str,
        *,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk | ExecutionResult, None]:
        if env:
            validate_env_keys(env)
        # The agent's shell sends its own timeout; file tools and the Workspaces API send none.
        seconds = math.ceil(timeout) if timeout else self.default_timeout
        body = {"command": command, "timeout": seconds, "cwd": cwd, "env": env}
        # shortcut: output is kept in full for the tool result, so a command printing gigabytes grows api memory; cap it before multi-user hosting.
        stdout: list[str] = []
        stderr: list[str] = []
        # Leaving this block early (the turn was cancelled) closes the connection, and the runner
        # kills the jail when its client goes away.
        async with runner_client(self.socket_path) as client:
            async with client.stream("POST", f"/workspaces/{self.workspace_id}/exec", json=body) as response:
                await raise_for_runner_error(response)
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    item = json.loads(line)
                    if "exit_code" in item:
                        if item["timed_out"]:
                            raise SandboxTimeoutError(seconds, "".join(stdout), "".join(stderr))
                        yield ExecutionResult(item["exit_code"], "".join(stdout), "".join(stderr))
                        return
                    (stderr if item["stream"] == "stderr" else stdout).append(item["data"])
                    yield StreamChunk(item["data"], item["stream"])
        raise OSError("The runner stream ended before the command finished.")
