"""The agent's tool for servers and watchers that must outlive one shell command. Each one runs in
the workspace's jail and network, so the agent's later commands reach it on localhost and the user
can open its port in the Preview panel."""

import asyncio
import json
from typing import Literal

from strands import tool

from core.config import Settings
from sandbox import processes

# How long `start` waits before reporting the first log lines and ports, so a server that crashes
# at once or binds the wrong port is seen in the same call.
SETTLE_SECONDS = 2
START_LOG_LINES = 30


def process_tool(settings: Settings, workspace_id: str):
    socket = settings.runner_socket

    @tool
    async def process(action: Literal["start", "stop", "list", "logs"], name: str = "", command: str = "", cwd: str = "", tail: int = 100) -> str:
        """Starts, stops and inspects long-running processes in the workspace, such as dev servers and file watchers, which keep running after the call returns. Use it instead of `&` or `nohup` in the shell, which do not survive the command.

        Args:
            action: "start" runs `command` under `name`; "stop" stops `name`; "list" shows every process and the ports listening in the workspace; "logs" shows the last `tail` lines of `name`'s output.
            name: The process's name, 1 to 32 lowercase letters, digits and dashes, such as "web" or "watch". Needed for start, stop and logs.
            command: The sh command to run, for start. Bind servers to localhost or 0.0.0.0.
            cwd: Folder to run in, for start; the workspace root by default.
            tail: How many log lines to show, for logs, at most 1000.
        """
        if action == "list":
            return json.dumps(await processes.list_all(socket, workspace_id))
        if not name:
            raise ValueError(f"`{action}` needs a name.")
        if action == "start":
            if not command:
                raise ValueError("`start` needs a command.")
            started = await processes.start(socket, workspace_id, name, command, cwd or None)
            await asyncio.sleep(SETTLE_SECONDS)
            listed = await processes.list_all(socket, workspace_id)
            now = next((p for p in listed["processes"] if p["name"] == name), started)
            log = (await processes.logs(socket, workspace_id, name, START_LOG_LINES))["log"]
            return json.dumps({"process": now, "ports": listed["ports"], "log": log})
        if action == "stop":
            return json.dumps(await processes.stop(socket, workspace_id, name))
        if action == "logs":
            return json.dumps(await processes.logs(socket, workspace_id, name, max(1, min(tail, 1000))))
        raise ValueError(f"Unknown action {action!r}.")

    return process
