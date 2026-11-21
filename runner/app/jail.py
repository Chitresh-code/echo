"""Builds the nsjail command line for one workspace command, and runs it.

Every jail runs as uid and gid 1000 (mapped to 1000 outside, so its files are owned by the same
user the runner creates workspaces for), sees only its own workspace and home, read-only system
directories and a private /tmp, and gets no environment except what is listed here."""

import asyncio
import codecs
import os
import re
import signal
import tempfile
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path

JAIL_UID = 1000
WORKSPACE_ID = re.compile(r"[0-9a-f]{32}")
ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# nsjail kills a jail at its time limit with SIGKILL, which the shell reports as 128 + 9.
KILLED_EXIT = 137
# How long after the time limit the runner kills nsjail itself, in case nsjail hangs.
BACKSTOP_SECONDS = 5
# How long a jail gets to exit after SIGTERM before it is killed.
KILL_GRACE_SECONDS = 2


class JailError(Exception):
    """A request the runner refuses before starting a jail. `code` is stable for callers."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    network: bool
    timeout_max: int
    memory_mb: int
    nsjail: str = "nsjail"


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    return Settings(
        data_dir=Path(env.get("RUNNER_DATA_DIR", "/data")),
        network=env.get("RUNNER_JAIL_NETWORK", "1") == "1",
        timeout_max=int(env.get("RUNNER_TIMEOUT_MAX", "1800")),
        memory_mb=int(env.get("RUNNER_JAIL_MEMORY_MB", "4096")),
    )


def check_id(workspace_id: str) -> str:
    if not WORKSPACE_ID.fullmatch(workspace_id):
        raise JailError("invalid_workspace_id", "A workspace id is 32 lowercase hex characters.")
    return workspace_id


def workspace_dir(settings: Settings, workspace_id: str) -> Path:
    return settings.data_dir / "workspaces" / check_id(workspace_id)


def home_dir(settings: Settings, workspace_id: str) -> Path:
    return settings.data_dir / "homes" / check_id(workspace_id)


def commands_dir(settings: Settings) -> Path:
    return settings.data_dir / "commands"


def write_script(settings: Settings, command: str) -> Path:
    """Write the command to a file the jail runs, readable but not writable by the jail.

    Linux caps a single argv item at 128 KB, and file writes travel inside the command as base64,
    so the command cannot be an argument to `sh -c`."""
    if "\0" in command:
        raise JailError("invalid_command", "The command contains a NUL byte.")
    fd, name = tempfile.mkstemp(dir=commands_dir(settings), suffix=".sh")
    with os.fdopen(fd, "w") as f:
        f.write(command)
    os.chmod(name, 0o644)
    return Path(name)


def effective_timeout(settings: Settings, timeout: int | None) -> int:
    if timeout is None:
        return settings.timeout_max
    if timeout < 1:
        raise JailError("invalid_timeout", "The timeout must be at least one second.")
    return min(timeout, settings.timeout_max)


def _check_cwd(workspace: Path, cwd: str | None) -> str:
    if cwd is None:
        return str(workspace)
    if "\0" in cwd or not cwd.startswith("/"):
        raise JailError("invalid_cwd", "The working directory must be an absolute path in the workspace.")
    normal = os.path.normpath(cwd)
    if normal != str(workspace) and not normal.startswith(f"{workspace}/"):
        raise JailError("invalid_cwd", "The working directory must be in the workspace.")
    return normal


def _check_env(env: Mapping[str, str] | None) -> list[str]:
    pairs = []
    for key, value in (env or {}).items():
        if not ENV_KEY.fullmatch(key):
            raise JailError("invalid_env", f"{key!r} is not a valid environment variable name.")
        if "\0" in value:
            raise JailError("invalid_env", f"The value of {key} contains a NUL byte.")
        pairs.append(f"{key}={value}")
    return pairs


def build_argv(
    settings: Settings,
    workspace_id: str,
    script: Path,
    timeout: int,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    lib64_exists: bool | None = None,
) -> list[str]:
    workspace = workspace_dir(settings, workspace_id)
    home = home_dir(settings, workspace_id)
    if lib64_exists is None:
        lib64_exists = os.path.isdir("/lib64")

    argv = [
        settings.nsjail, "-Mo", "--really_quiet",
        "-u", f"{JAIL_UID}:{JAIL_UID}", "-g", f"{JAIL_UID}:{JAIL_UID}",
        "-t", str(timeout),
        # nsjail's own defaults (1 MB files, 32 open files, 600 s of CPU) are too small for
        # package installs and builds, so every limit is set here.
        # shortcut: rlimits only, no cgroup memory, process or CPU share limits and no seccomp policy; add them before Echo is open to the public.
        "--rlimit_as", str(settings.memory_mb),
        "--rlimit_cpu", str(timeout),
        "--rlimit_fsize", "1024",
        "--rlimit_nofile", "1024",
        "-R", "/bin", "-R", "/lib",
    ]
    if lib64_exists:
        argv += ["-R", "/lib64"]
    argv += [
        "-R", "/usr", "-R", "/etc",
        "-R", "/dev/null", "-R", "/dev/zero", "-R", "/dev/random", "-R", "/dev/urandom",
        # The command file, at the same path as outside; the jail sees no other file in its directory.
        "-R", str(script),
        "--tmpfsmount", "/tmp",
        # Same absolute path as in the sandbox container, so paths mean the same everywhere.
        "-B", str(workspace),
        "-B", f"{home}:/home/echo",
        "--cwd", _check_cwd(workspace, cwd),
        "-E", "HOME=/home/echo",
        "-E", "PATH=/home/echo/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "-E", "LANG=C.UTF-8",
        "-E", "NPM_CONFIG_PREFIX=/home/echo/.local",
        "-E", "GIT_AUTHOR_NAME=Echo", "-E", "GIT_AUTHOR_EMAIL=agent@echo.local",
        "-E", "GIT_COMMITTER_NAME=Echo", "-E", "GIT_COMMITTER_EMAIL=agent@echo.local",
    ]
    for pair in _check_env(env):
        argv += ["-E", pair]
    if settings.network:
        # Share the sandbox container's network, where the firewall on uid 1000 applies. Without
        # this the jail gets an empty network namespace and no internet.
        # shortcut: one shared network for every jail, so loopback is blocked and outbound is open to any public address; a network namespace per workspace fixes the first, abuse controls the second.
        argv.append("--disable_clone_newnet")
    # The command is only ever read by the shell inside the jail, never parsed outside it.
    argv += ["--", "/bin/sh", str(script)]
    return argv


@dataclass
class Chunk:
    stream: str
    data: str


@dataclass
class Exit:
    exit_code: int
    timed_out: bool


async def run(argv: list[str], timeout: int) -> AsyncIterator[Chunk | Exit]:
    """Run a jail and yield its output as it arrives, then its exit. If the caller stops iterating
    (the client went away), the jail is killed."""
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    queue: asyncio.Queue[Chunk | None] = asyncio.Queue()

    async def pump(reader: asyncio.StreamReader, name: str):
        # Incremental decoding, so a character split across two reads is not mangled.
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while data := await reader.read(65536):
            if text := decoder.decode(data):
                await queue.put(Chunk(name, text))
        if tail := decoder.decode(b"", final=True):
            await queue.put(Chunk(name, tail))
        await queue.put(None)

    started = time.monotonic()
    pumps = [asyncio.create_task(pump(proc.stdout, "stdout")), asyncio.create_task(pump(proc.stderr, "stderr"))]
    deadline = started + timeout + BACKSTOP_SECONDS
    backstop_hit = False
    try:
        open_streams = 2
        while open_streams:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=max(deadline - time.monotonic(), 0))
            except TimeoutError:
                backstop_hit = True
                break
            if item is None:
                open_streams -= 1
            else:
                yield item
        if backstop_hit:
            await _stop(proc)
        exit_code = await proc.wait()
        elapsed = time.monotonic() - started
        yield Exit(exit_code, backstop_hit or (exit_code == KILLED_EXIT and elapsed >= timeout))
    finally:
        if proc.returncode is None:
            await _stop(proc)
        for task in pumps:
            task.cancel()


async def _stop(proc: asyncio.subprocess.Process) -> None:
    # SIGTERM lets nsjail kill the jailed process tree; SIGKILL if it does not exit in time.
    try:
        proc.send_signal(signal.SIGTERM)
        await asyncio.wait_for(proc.wait(), KILL_GRACE_SECONDS)
    except ProcessLookupError:
        return
    except TimeoutError:
        proc.kill()
        await proc.wait()
