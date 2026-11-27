"""Local MCP servers: a command the user chose, run in the workspace's jail with its stdin and stdout
as the MCP stdio transport. The api writes messages with one request each and reads the server's
messages from one long stream; when that stream closes for any reason the jail is killed, so a
server never outlives the turn that started it.

The table is in memory: a runner restart kills every jail, so there is nothing to recover."""

import asyncio
import collections
import contextlib
import json
import re
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from app import jail, processes

MAX_PER_WORKSPACE = 5
# One message either way; a server writing a longer line is killed rather than buffered.
MAX_MESSAGE = 4 * 1024 * 1024
COMMAND_MAX = 500
ARGS_MAX = 50
ARG_MAX = 1000
ENV_MAX = 20
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
# Set by the jail for every command; a server's environment cannot replace them.
PROTECTED = {"HOME", "PATH", "LANG", "TERM", "NPM_CONFIG_PREFIX", "GIT_OPTIONAL_LOCKS",
             "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"}
STDERR_KEEP = 64 * 1024
STDERR_SENT = 2000
SESSION_ID = re.compile(r"[0-9a-f]{32}")


@dataclass
class Session:
    id: str
    workspace_id: str
    proc: asyncio.subprocess.Process
    stderr: collections.deque = field(default_factory=lambda: collections.deque(maxlen=STDERR_KEEP))
    reading: bool = False
    pump: asyncio.Task | None = None

    @property
    def ended(self) -> bool:
        return self.proc.returncode is not None

    def stderr_tail(self) -> str:
        return bytes(self.stderr).decode(errors="replace")[-STDERR_SENT:]


def check_program(command: str, args: list[str], env: dict[str, str]) -> None:
    if not command or len(command) > COMMAND_MAX or len(args) > ARGS_MAX or any(len(a) > ARG_MAX for a in args):
        raise jail.JailError("invalid_mcp_command", f"The command is 1 to {COMMAND_MAX} characters, with at most {ARGS_MAX} arguments of {ARG_MAX} each.")
    if "\0" in command or any("\0" in a for a in args):
        raise jail.JailError("invalid_mcp_command", "The command contains a NUL byte.")
    if len(env) > ENV_MAX:
        raise jail.JailError("invalid_env", f"A server has at most {ENV_MAX} environment variables.")
    for name in env:
        if not ENV_NAME.fullmatch(name) or name in PROTECTED or name.startswith("NSJAIL"):
            raise jail.JailError("invalid_env", f"{name!r} cannot be set for an MCP server.")


class Sessions:
    """Counts against the sandbox-wide process limit with the background processes, under the
    same lock, so the two cannot together pass it."""

    def __init__(self, settings: jail.Settings, registry: processes.Registry):
        self.settings, self.registry = settings, registry
        self.table: dict[str, dict[str, Session]] = {}
        registry.others = self.count

    def count(self, workspace_id: str | None = None) -> int:
        tables = [self.table.get(workspace_id, {})] if workspace_id else self.table.values()
        return sum(not s.ended for t in tables for s in t.values())

    def get(self, workspace_id: str, session_id: str) -> Session:
        session = self.table.get(workspace_id, {}).get(session_id) if SESSION_ID.fullmatch(session_id) else None
        if session is None:
            raise jail.JailError("mcp_session_not_found", "There is no MCP session with this id.", 404)
        return session

    async def start(self, workspace_id: str, command: str, args: list[str], env: dict[str, str], argv_for) -> Session:
        """`argv_for(program, timeout)` returns the jail argv running `program`."""
        check_program(command, args, env)
        async with self.registry.lock:
            if self.count(workspace_id) >= MAX_PER_WORKSPACE:
                raise jail.JailError("too_many_mcp_servers", f"A workspace runs at most {MAX_PER_WORKSPACE} MCP servers at once.", 409)
            if self.count() + self.registry.running_count() >= self.settings.max_processes:
                raise jail.JailError("too_many_processes", "The sandbox is running as many processes as it can; try again later.", 429)
            argv = await argv_for([command, *args], self.settings.process_timeout)
            proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=MAX_MESSAGE + 1,
            )
            session = Session(secrets.token_hex(16), workspace_id, proc)
            session.pump = asyncio.create_task(self._keep_stderr(session))
            self.table.setdefault(workspace_id, {})[session.id] = session
            return session

    async def _keep_stderr(self, session: Session) -> None:
        while data := await session.proc.stderr.read(65536):
            session.stderr.extend(data)

    def claim(self, session: Session) -> None:
        """Before the stream starts, so a second reader gets an error response, not a broken stream."""
        if session.reading:
            raise jail.JailError("mcp_session_busy", "This MCP session is already being read.", 409)
        session.reading = True

    async def messages(self, session: Session) -> AsyncIterator[dict]:
        """The server's messages, then its exit. The jail is killed when this ends, however it ends."""
        try:
            while True:
                try:
                    line = await session.proc.stdout.readline()
                except ValueError:
                    session.stderr.extend(b"\n[echo] The server wrote a message over 4 MB, so it was stopped.")
                    break
                if not line:
                    break
                try:
                    message = json.loads(line)
                except ValueError:
                    message = None
                if not isinstance(message, dict):
                    session.stderr.extend(b"\n[echo] The server wrote something that is not a JSON message to stdout, so it was stopped.")
                    break
                yield {"message": message}
            await self.stop(session)
            yield {"exit": session.proc.returncode, "stderr": session.stderr_tail()}
        finally:
            await self.stop(session)
            self.table.get(session.workspace_id, {}).pop(session.id, None)

    async def send(self, session: Session, message: dict) -> None:
        if session.ended or session.proc.stdin.is_closing():
            raise jail.JailError("mcp_session_ended", "The MCP server has exited.", 409)
        session.proc.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        try:
            await session.proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            raise jail.JailError("mcp_session_ended", "The MCP server has exited.", 409) from None

    async def stop(self, session: Session) -> None:
        if not session.ended:
            await jail._stop(session.proc)
        if session.pump:
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(session.pump), jail.KILL_GRACE_SECONDS)

    async def remove(self, session: Session) -> None:
        await self.stop(session)
        self.table.get(session.workspace_id, {}).pop(session.id, None)

    async def stop_workspace(self, workspace_id: str) -> None:
        for session in list(self.table.pop(workspace_id, {}).values()):
            await self.stop(session)

    async def stop_all(self) -> None:
        for workspace_id in list(self.table):
            await self.stop_workspace(workspace_id)
