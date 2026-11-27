"""The MCP stdio transport for a local server, which runs in the workspace's jail. The runner holds
the server's stdin and stdout: each message to the server is one request, and the server's messages
come back on one long NDJSON stream. Closing that stream makes the runner kill the jail, so leaving
the transport, however it is left, stops the server."""

import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import anyio
import httpx
from mcp import types
from mcp.shared.message import SessionMessage

from sandbox.runner_sandbox import raise_for_runner_error, runner_client

logger = logging.getLogger(__name__)


@dataclass
class Local:
    """A local server as a turn starts it. `stderr` holds the end of the server's error output once it
    has exited, for telling the user why it failed."""

    workspace_id: str
    socket_path: Path
    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)
    stderr: str = ""
    exited: bool = False


@contextlib.asynccontextmanager
async def transport(local: Local) -> AsyncIterator[tuple]:
    # Its own client: the SDK runs this on the MCP client's thread and loop, not the api's.
    async with runner_client(local.socket_path) as runner:
        base = f"/workspaces/{local.workspace_id}/mcp"
        response = await runner.post(base, json={"command": local.command, "args": local.args, "env": local.env})
        await raise_for_runner_error(response)
        messages = f"{base}/{response.json()['data']['id']}/messages"

        read_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
        write_stream, write_reader = anyio.create_memory_object_stream[SessionMessage](0)

        async def read() -> None:
            async with read_writer, runner.stream("GET", messages) as stream:
                await raise_for_runner_error(stream)
                async for line in stream.aiter_lines():
                    if not line:
                        continue
                    item = json.loads(line)
                    if "exit" in item:
                        local.exited, local.stderr = True, item.get("stderr") or ""
                        logger.info("Local MCP server %s in %s exited with %s", local.command, local.workspace_id, item["exit"])
                        return
                    try:
                        parsed: SessionMessage | Exception = SessionMessage(types.jsonrpc_message_adapter.validate_python(item["message"], by_name=False))
                    except ValueError as exc:
                        # As the SDK's stdio client does: the session surfaces a bad message as an error.
                        parsed = exc
                    await read_writer.send(parsed)

        async def write() -> None:
            async with write_reader:
                async for message in write_reader:
                    body = message.message.model_dump_json(by_alias=True, exclude_unset=True)
                    sent = await runner.post(messages, content=body, headers={"content-type": "application/json"})
                    if sent.status_code == 409:
                        # The server exited; the read side reports how.
                        return
                    await raise_for_runner_error(sent)

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(read)
                tg.start_soon(write)
                try:
                    yield read_stream, write_stream
                finally:
                    tg.cancel_scope.cancel()
        finally:
            # The stream closing already stopped the jail; this removes a session that never got read.
            with anyio.CancelScope(shield=True), anyio.move_on_after(5), contextlib.suppress(httpx.HTTPError):
                await runner.delete(messages.removesuffix("/messages"))
