"""Terminals: an interactive bash in a workspace's jail, on a pseudo terminal the runner holds.

A terminal outlives the socket that watches it, like a process does, so a reloaded page or a
dropped connection attaches again and gets the recent output replayed. It ends when its shell
exits, when it is deleted, after `terminal_idle` seconds with nothing attached, or at its time
limit. The table is in memory: a runner restart ends every shell, as it does every jail."""

import asyncio
import contextlib
import fcntl
import logging
import os
import pty
import struct
import termios
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app import jail

logger = logging.getLogger("runner.terminals")

# Output kept for a socket that attaches later. A replay can start mid escape sequence, which a
# terminal shows as a stray character or two at the top; it does not upset what follows.
SCROLLBACK_BYTES = 256 * 1024
# Chunks waiting for one slow socket before it is dropped; its page reconnects and replays.
SOCKET_QUEUE = 512
# How long input may wait for a shell that is not reading before it is dropped.
WRITE_WAIT_SECONDS = 5
SWEEP_SECONDS = 60
MAX_COLS, MAX_ROWS = 1000, 500
# Run by sh, it starts bash with itself as the startup file; read by bash, it loads the user's
# own ~/.bashrc and sets a prompt. The system one would show "I have no name!", since the jail's
# uid has no entry in the image's /etc/passwd.
COMMAND = r"""if [ -z "$ECHO_TERMINAL" ]; then ECHO_TERMINAL=1 exec /bin/bash --rcfile "$0" -i; fi
[ -f ~/.bashrc ] && . ~/.bashrc
PROMPT_DIRTRIM=2
PS1='\[\e[1;34m\]\w\[\e[0m\] \$ '
"""


def check_id(terminal_id: str) -> str:
    if not jail.WORKSPACE_ID.fullmatch(terminal_id):
        raise jail.JailError("invalid_terminal_id", "A terminal id is 32 lowercase hex characters.")
    return terminal_id


def set_size(fd: int, cols: int, rows: int) -> None:
    cols, rows = max(1, min(cols, MAX_COLS)), max(1, min(rows, MAX_ROWS))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


@dataclass
class Terminal:
    id: str
    workspace_id: str
    master: int
    proc: asyncio.subprocess.Process
    script: Path
    started_at: float = field(default_factory=time.time)
    scrollback: bytearray = field(default_factory=bytearray)
    # One queue per attached socket; None in a queue means the shell has exited.
    sockets: set[asyncio.Queue] = field(default_factory=set)
    detached_at: float | None = field(default_factory=time.monotonic)
    exit_code: int | None = None
    ended: asyncio.Event = field(default_factory=asyncio.Event)

    def to_json(self) -> dict:
        return {"id": self.id, "started_at": self.started_at, "attached": len(self.sockets)}

    def attach(self) -> asyncio.Queue:
        """A queue that starts with the scrollback and then gets every new chunk. Synchronous, so
        no output can land between the snapshot and the subscription."""
        queue: asyncio.Queue = asyncio.Queue(SOCKET_QUEUE)
        if self.scrollback:
            queue.put_nowait(bytes(self.scrollback))
        if self.ended.is_set():
            queue.put_nowait(None)
        else:
            self.sockets.add(queue)
            self.detached_at = None
        return queue

    def detach(self, queue: asyncio.Queue) -> None:
        self.sockets.discard(queue)
        if not self.sockets:
            self.detached_at = time.monotonic()

    def _output(self, data: bytes) -> None:
        self.scrollback += data
        if len(self.scrollback) > SCROLLBACK_BYTES:
            del self.scrollback[: len(self.scrollback) - SCROLLBACK_BYTES]
        for queue in list(self.sockets):
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                # Too slow to keep up: dropped, with an end marker in place of its oldest chunk.
                self.sockets.discard(queue)
                queue.get_nowait()
                queue.put_nowait(None)

    async def write(self, data: bytes) -> None:
        deadline = time.monotonic() + WRITE_WAIT_SECONDS
        while data and not self.ended.is_set():
            try:
                data = data[os.write(self.master, data):]
            except BlockingIOError:
                if time.monotonic() > deadline:
                    return
                await asyncio.sleep(0.01)
            except OSError:
                return

    def resize(self, cols: int, rows: int) -> None:
        with contextlib.suppress(OSError):
            set_size(self.master, cols, rows)


class Terminals:
    def __init__(self, settings: jail.Settings):
        self.settings = settings
        self.table: dict[str, dict[str, Terminal]] = {}
        self.lock = asyncio.Lock()
        self.sweeper: asyncio.Task | None = None

    def get(self, workspace_id: str, terminal_id: str) -> Terminal:
        terminal = self.table.get(workspace_id, {}).get(check_id(terminal_id))
        if terminal is None:
            raise jail.JailError("terminal_not_found", "There is no terminal with this id. It may have ended.", 404)
        return terminal

    def list(self, workspace_id: str) -> list[dict]:
        return [t.to_json() for t in sorted(self.table.get(workspace_id, {}).values(), key=lambda t: t.started_at)]

    async def start(self, workspace_id: str, argv_for, cols: int, rows: int, note: str = "") -> Terminal:
        """`argv_for(timeout, tty)` writes the command file and returns (argv, script), as for exec."""
        async with self.lock:
            if len(self.table.get(workspace_id, {})) >= self.settings.max_terminals_per_workspace:
                raise jail.JailError("too_many_terminals", f"A workspace can have at most {self.settings.max_terminals_per_workspace} terminals open; close one first.", 409)
            if sum(len(t) for t in self.table.values()) >= self.settings.max_terminals:
                raise jail.JailError("too_many_terminals", "The sandbox has as many terminals open as it can; try again later.", 429)
            master, slave = pty.openpty()
            try:
                argv, script = await argv_for(self.settings.terminal_timeout, os.ttyname(slave))
            except BaseException:
                os.close(master)
                os.close(slave)
                raise
            try:
                set_size(master, cols, rows)
                os.set_blocking(master, False)
                # A new session whose controlling terminal is the pty, which the shell keeps through
                # nsjail's --skip_setsid, so job control and Ctrl+C work.
                proc = await asyncio.create_subprocess_exec(
                    *argv, stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                    preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0),
                )
            except BaseException:
                os.close(master)
                script.unlink(missing_ok=True)
                raise
            finally:
                # Only the jail holds the slave now, so the master reads EOF when the shell is gone.
                os.close(slave)
            terminal = Terminal(uuid.uuid4().hex, workspace_id, master, proc, script)
            if note:
                terminal._output(note.replace("\n", "\r\n").encode())
            asyncio.get_running_loop().add_reader(master, self._read, terminal)
            self.table.setdefault(workspace_id, {})[terminal.id] = terminal
            self._sweep_later()
            return terminal

    def _read(self, terminal: Terminal) -> None:
        try:
            data = os.read(terminal.master, 65536)
        except BlockingIOError:
            return
        except OSError:
            # EIO: every process holding the terminal has gone.
            data = b""
        if data:
            terminal._output(data)
        else:
            asyncio.get_running_loop().remove_reader(terminal.master)
            asyncio.create_task(self._finish(terminal))

    async def _finish(self, terminal: Terminal) -> None:
        if terminal.ended.is_set():
            return
        terminal.ended.set()
        with contextlib.suppress(ValueError):
            asyncio.get_running_loop().remove_reader(terminal.master)
        if terminal.proc.returncode is None:
            # The shell is gone but nsjail may linger for a moment; bounded, then stopped.
            try:
                await asyncio.wait_for(terminal.proc.wait(), jail.KILL_GRACE_SECONDS)
            except TimeoutError:
                await jail._stop(terminal.proc)
        terminal.exit_code = terminal.proc.returncode
        with contextlib.suppress(OSError):
            os.close(terminal.master)
        terminal.script.unlink(missing_ok=True)
        for queue in list(terminal.sockets):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)
        terminal.sockets.clear()
        self.table.get(terminal.workspace_id, {}).pop(terminal.id, None)

    async def stop(self, terminal: Terminal) -> None:
        if terminal.proc.returncode is None:
            await jail._stop(terminal.proc)
        await self._finish(terminal)

    async def stop_workspace(self, workspace_id: str) -> None:
        for terminal in list(self.table.get(workspace_id, {}).values()):
            await self.stop(terminal)
        self.table.pop(workspace_id, None)

    async def stop_all(self) -> None:
        if self.sweeper:
            self.sweeper.cancel()
        for workspace_id in list(self.table):
            await self.stop_workspace(workspace_id)

    async def sweep(self) -> None:
        """End terminals nobody has watched for `terminal_idle` seconds."""
        now = time.monotonic()
        for table in list(self.table.values()):
            for terminal in list(table.values()):
                if terminal.detached_at is not None and now - terminal.detached_at > self.settings.terminal_idle:
                    logger.info("Ending terminal %s of %s: unattached for %s s", terminal.id, terminal.workspace_id, self.settings.terminal_idle)
                    await self.stop(terminal)

    def _sweep_later(self) -> None:
        if self.sweeper and not self.sweeper.done():
            return

        async def loop():
            while any(self.table.values()):
                await asyncio.sleep(SWEEP_SECONDS)
                await self.sweep()

        self.sweeper = asyncio.create_task(loop())
