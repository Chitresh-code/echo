"""Long-running processes: a named command per workspace (a dev server, a watcher) that outlives
the request that started it. Each one is an ordinary jail in the workspace's network namespace
with a long time limit instead of the command timeout. Its output goes to a capped log file
outside the workspace and home, so the agent cannot read or fill another process's log through
its own files.

The table is in memory: a runner restart kills every jail, so there is nothing to recover."""

import asyncio
import contextlib
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from app import jail

NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
# A log is cut back to its last LOG_KEEP bytes whenever it passes LOG_MAX.
LOG_MAX = 1024 * 1024
LOG_KEEP = 512 * 1024
# What one logs request returns at most.
TAIL_LINES_MAX = 1000
TAIL_BYTES_MAX = 256 * 1024
# The TCP state LISTEN in /proc/net/tcp.
LISTEN = "0A"


@dataclass
class Process:
    name: str
    command: str
    cwd: str | None
    started_at: float
    log_path: Path
    script: Path
    proc: asyncio.subprocess.Process | None = None
    exit_code: int | None = None
    pump: asyncio.Task | None = field(default=None, repr=False)

    @property
    def running(self) -> bool:
        return self.pump is not None and not self.pump.done()

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "command": self.command,
            "cwd": self.cwd,
            "status": "running" if self.running else "exited",
            "exit_code": self.exit_code,
            "started_at": self.started_at,
        }


def check_name(name: str) -> str:
    if not NAME.fullmatch(name):
        raise jail.JailError("invalid_process_name", "A process name is 1 to 32 lowercase letters, digits and dashes, starting with a letter or digit.")
    return name


def logs_dir(settings: jail.Settings, workspace_id: str) -> Path:
    return settings.data_dir / "processes" / jail.check_id(workspace_id)


def append_log(path: Path, data: bytes) -> None:
    """Append to the log, cutting it back to its last LOG_KEEP bytes once it passes LOG_MAX."""
    with open(path, "ab") as f:
        f.write(data)
        size = f.tell()
    if size > LOG_MAX:
        with open(path, "rb") as f:
            f.seek(-LOG_KEEP, os.SEEK_END)
            kept = f.read()
        # Start at a line, so the log does not open mid-line.
        if (nl := kept.find(b"\n")) != -1:
            kept = kept[nl + 1 :]
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(kept)
        os.replace(tmp, path)


def tail(path: Path, lines: int) -> str:
    lines = max(1, min(lines, TAIL_LINES_MAX))
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(f.tell() - TAIL_BYTES_MAX, 0))
            data = f.read()
    except FileNotFoundError:
        return ""
    return "\n".join(data.decode(errors="replace").splitlines()[-lines:])


def parse_listening(text: str) -> set[int]:
    """Ports in LISTEN in the contents of /proc/<pid>/net/tcp or tcp6."""
    ports = set()
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) > 3 and parts[3] == LISTEN:
            ports.add(int(parts[1].rsplit(":", 1)[1], 16))
    return ports


def listening_ports(pid: int) -> list[int]:
    """The TCP ports listening in the network namespace of `pid`, which is the workspace's, so
    this covers every server in the workspace whichever process started it."""
    ports: set[int] = set()
    for name in ("tcp", "tcp6"):
        with contextlib.suppress(OSError):
            ports |= parse_listening(Path(f"/proc/{pid}/net/{name}").read_text())
    return sorted(ports)


class Registry:
    def __init__(self, settings: jail.Settings):
        self.settings = settings
        self.table: dict[str, dict[str, Process]] = {}
        # Held from the limit check to the process being in the table, so two starts cannot both pass.
        self.lock = asyncio.Lock()

    def running_count(self, workspace_id: str | None = None) -> int:
        tables = [self.table.get(workspace_id, {})] if workspace_id else self.table.values()
        return sum(p.running for t in tables for p in t.values())

    def get(self, workspace_id: str, name: str) -> Process:
        process = self.table.get(workspace_id, {}).get(check_name(name))
        if process is None:
            raise jail.JailError("process_not_found", "There is no process with this name.", 404)
        return process

    def list(self, workspace_id: str) -> dict:
        processes = sorted(self.table.get(workspace_id, {}).values(), key=lambda p: p.started_at)
        pid = next((p.proc.pid for p in processes if p.running and p.proc), None)
        return {"processes": [p.to_json() for p in processes], "ports": listening_ports(pid) if pid else []}

    async def start(self, workspace_id: str, name: str, command: str, argv_for, cwd: str | None, note: str = "") -> Process:
        """`argv_for(timeout)` writes the command file and returns (argv, script), as for exec.
        `note` starts the log, for a warning the process's own output would not explain."""
        check_name(name)
        async with self.lock:
            existing = self.table.get(workspace_id, {}).get(name)
            if existing and existing.running:
                raise jail.JailError("process_exists", f"A process named {name} is already running.", 409)
            if self.running_count(workspace_id) >= self.settings.max_processes_per_workspace:
                raise jail.JailError("too_many_processes", f"An agent can run at most {self.settings.max_processes_per_workspace} processes; stop one first.", 429)
            if self.running_count() >= self.settings.max_processes:
                raise jail.JailError("too_many_processes", "The sandbox is running as many processes as it can; try again later.", 429)
            argv, script = await argv_for(self.settings.process_timeout)
            folder = logs_dir(self.settings, workspace_id)
            folder.mkdir(parents=True, exist_ok=True)
            log = folder / f"{name}.log"
            log.unlink(missing_ok=True)
            fd = os.open(log, os.O_WRONLY | os.O_CREAT, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(note)
            process = Process(name, command, cwd, time.time(), log, script)
            try:
                process.proc = await asyncio.create_subprocess_exec(
                    *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                )
            except BaseException:
                script.unlink(missing_ok=True)
                raise
            process.pump = asyncio.create_task(self._pump(process))
            self.table.setdefault(workspace_id, {})[name] = process
            return process

    async def _pump(self, process: Process) -> None:
        try:
            while data := await process.proc.stdout.read(65536):
                await asyncio.to_thread(append_log, process.log_path, data)
            process.exit_code = await process.proc.wait()
        finally:
            process.script.unlink(missing_ok=True)

    async def stop(self, process: Process) -> None:
        if process.proc and process.proc.returncode is None:
            await jail._stop(process.proc)
        if process.pump:
            # A jail's processes die with nsjail, which closes the pipe; the wait is bounded anyway
            # so a stop never hangs on a pipe something else still holds.
            try:
                await asyncio.wait_for(asyncio.shield(process.pump), jail.KILL_GRACE_SECONDS)
            except TimeoutError:
                process.pump.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await process.pump
                process.exit_code = process.proc.returncode
            except asyncio.CancelledError:
                pass

    async def stop_workspace(self, workspace_id: str) -> None:
        """Stop the workspace's processes and drop them and their logs, when it is deleted."""
        for process in list(self.table.pop(workspace_id, {}).values()):
            await self.stop(process)
        for log in logs_dir(self.settings, workspace_id).glob("*"):
            log.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            logs_dir(self.settings, workspace_id).rmdir()

    async def stop_all(self) -> None:
        for workspace_id in list(self.table):
            for process in self.table[workspace_id].values():
                await self.stop(process)
