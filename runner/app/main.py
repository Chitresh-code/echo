"""The runner: the only process that starts jails. It listens on a Unix socket that only the api
container's user can open, and no network port, so neither a jail nor anything on the network
can ask it to run a command."""

import asyncio
import contextlib
import json
import logging
import os
import shutil
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Path as PathParam, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import jail, net, preview, processes, terminals, usage

logger = logging.getLogger("runner")


class ProcessRequest(BaseModel):
    name: str
    command: str = Field(max_length=100_000)
    cwd: str | None = None
    env: dict[str, str] | None = None


class TerminalRequest(BaseModel):
    cols: int = Field(80, ge=1, le=terminals.MAX_COLS)
    rows: int = Field(24, ge=1, le=terminals.MAX_ROWS)


# A paste larger than this is refused rather than queued into a shell that may not be reading.
TERMINAL_INPUT_MAX = 64 * 1024


class ExecRequest(BaseModel):
    # Room for a 5 MB file write, which travels base64 encoded inside the command.
    command: str = Field(max_length=8_000_000)
    timeout: int | None = None
    cwd: str | None = None
    env: dict[str, str] | None = None


def _error(status: int, code: str, message: str) -> JSONResponse:
    # Same shape as the api's errors, so the api can pass the code through.
    return JSONResponse(status_code=status, content={"success": False, "error": {"code": code, "message": message, "details": None}})


def create_app(settings: jail.Settings) -> FastAPI:
    registry = processes.Registry(settings)
    shells = terminals.Terminals(settings)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await shells.stop_all()
        await registry.stop_all()

    app = FastAPI(title="Echo runner", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    # Command files are removed after each run; clearing the directory at startup removes any
    # left by a crash.
    shutil.rmtree(jail.commands_dir(settings), ignore_errors=True)
    jail.commands_dir(settings).mkdir(parents=True)

    @app.exception_handler(jail.JailError)
    async def jail_error(request: Request, exc: jail.JailError):
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return _error(422, "validation_error", "The request is not valid.")

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        logger.error("Unhandled exception", exc_info=exc)
        return _error(500, "runner_error", "The runner failed.")

    async def prepare(workspace_id: str, command: str, timeout: int, cwd=None, env=None, fsize_mb: int = 1024, tty: str | None = None) -> tuple[list[str], Path]:
        await net.ensure(settings, workspace_id)
        script = jail.write_script(settings, command)
        try:
            return jail.build_argv(settings, workspace_id, script, timeout, cwd, env, fsize_mb=fsize_mb, tty=tty), script
        except BaseException:
            script.unlink()
            raise

    async def run_to_end(workspace_id: str, command: str) -> jail.Exit:
        argv, script = await prepare(workspace_id, command, 60)
        result = None
        try:
            async for item in jail.run(argv, 60):
                if isinstance(item, jail.Exit):
                    result = item
                else:
                    logger.info("%s %s: %s", workspace_id, item.stream, item.data.rstrip())
        finally:
            script.unlink()
        return result

    # Background measurements, held so they are not garbage collected mid-walk.
    tasks: set[asyncio.Task] = set()

    @app.get("/health")
    def health():
        return {"success": True, "data": {"status": "ok"}}

    @app.post("/workspaces/{workspace_id}")
    async def create_workspace(workspace_id: str):
        for path in (jail.workspace_dir(settings, workspace_id), jail.home_dir(settings, workspace_id)):
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                path.mkdir()
            except FileExistsError:
                continue
            # The only time the runner touches a workspace outside a jail: a directory it just
            # made, before any jail has run in it.
            os.chown(path, jail.JAIL_UID, jail.JAIL_UID)
        result = await run_to_end(workspace_id, "git init -q && mkdir -p .agent/skills")
        if result is None or result.exit_code != 0:
            logger.error("Setting up workspace %s exited with %s", workspace_id, result)
            return _error(500, "workspace_setup_failed", "The workspace could not be set up.")
        return {"success": True, "data": {"id": workspace_id}}

    @app.get("/workspaces")
    def list_workspaces():
        root = settings.data_dir / "workspaces"
        entries = [p for p in root.iterdir() if jail.WORKSPACE_ID.fullmatch(p.name)] if root.is_dir() else []
        entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return {"success": True, "data": [p.name for p in entries]}

    @app.get("/workspaces/{workspace_id}/usage")
    async def workspace_usage(workspace_id: str):
        if not jail.workspace_dir(settings, workspace_id).is_dir():
            return _error(404, "workspace_not_found", "There is no workspace with this id.")
        return {"success": True, "data": {"used_bytes": await usage.used(settings, workspace_id), "limit_bytes": usage.limit(settings)}}

    @app.delete("/workspaces/{workspace_id}")
    async def delete_workspace(workspace_id: str):
        folders = [jail.workspace_dir(settings, workspace_id), jail.home_dir(settings, workspace_id)]
        if not any(f.exists() for f in folders):
            return _error(404, "workspace_not_found", "There is no workspace with this id.")
        # Before the folders go, so no process is left writing into them.
        await shells.stop_workspace(workspace_id)
        await registry.stop_workspace(workspace_id)
        for folder in folders:
            # rmtree removes a link the agent made instead of following it. Off the event loop,
            # since a large workspace takes a while.
            await asyncio.to_thread(shutil.rmtree, folder, ignore_errors=True)
        usage.forget(workspace_id)
        await net.remove(settings, workspace_id)
        if any(f.exists() for f in folders):
            logger.error("Workspace %s was not fully removed", workspace_id)
            return _error(500, "workspace_delete_failed", "The workspace could not be fully removed.")
        return {"success": True, "data": {"deleted": True}}

    @app.post("/workspaces/{workspace_id}/exec")
    async def exec_command(workspace_id: str, body: ExecRequest):
        if not jail.workspace_dir(settings, workspace_id).is_dir():
            return _error(404, "workspace_not_found", "There is no workspace with this id.")
        timeout = jail.effective_timeout(settings, body.timeout)
        used, limit = await usage.used(settings, workspace_id), usage.limit(settings)
        # Over the limit the jail can still read and delete, so the agent can clean up, but not write.
        full = used > limit
        # Built before the response starts, so a bad request is a 400, not a broken stream.
        argv, script = await prepare(workspace_id, body.command, timeout, body.cwd, body.env, fsize_mb=0 if full else 1024)

        async def lines() -> AsyncIterator[bytes]:
            # When the client disconnects, Starlette cancels this generator, and closing jail.run
            # kills the jail.
            try:
                if full:
                    yield (json.dumps({"stream": "stderr", "data": usage.over_limit_message(used, limit)}) + "\n").encode()
                async for item in jail.run(argv, timeout):
                    if isinstance(item, jail.Exit):
                        line = {"exit_code": item.exit_code, "timed_out": item.timed_out}
                    else:
                        line = {"stream": item.stream, "data": item.data}
                    yield (json.dumps(line) + "\n").encode()
            finally:
                script.unlink(missing_ok=True)
                # In the background, so the response is not held while a large workspace is walked.
                # shortcut: one command can overshoot the limit before this catches it; a filesystem quota per workspace would stop it at the limit.
                tasks.add(task := asyncio.create_task(usage.measure(settings, workspace_id)))
                task.add_done_callback(tasks.discard)

        return StreamingResponse(lines(), media_type="application/x-ndjson")

    def check_workspace(workspace_id: str) -> None:
        if not jail.workspace_dir(settings, workspace_id).is_dir():
            raise jail.JailError("workspace_not_found", "There is no workspace with this id.", 404)

    @app.post("/workspaces/{workspace_id}/processes")
    async def start_process(workspace_id: str, body: ProcessRequest):
        check_workspace(workspace_id)
        used, limit = await usage.used(settings, workspace_id), usage.limit(settings)
        # The same rule as exec: over the limit a process can read and delete, but not write.
        full = used > limit

        async def argv_for(timeout: int):
            return await prepare(workspace_id, body.command, timeout, body.cwd, body.env, fsize_mb=0 if full else 1024)

        note = usage.over_limit_message(used, limit) if full else ""
        process = await registry.start(workspace_id, body.name, body.command, argv_for, body.cwd, note)
        return {"success": True, "data": process.to_json()}

    @app.get("/workspaces/{workspace_id}/processes")
    def list_processes(workspace_id: str):
        check_workspace(workspace_id)
        data = registry.list(workspace_id)
        if not data["ports"]:
            # Ports are read through a process inside the workspace's network namespace; with no
            # background process running, an open shell is one (a server started from a terminal).
            pid = next((t.proc.pid for t in shells.table.get(workspace_id, {}).values() if t.proc.returncode is None), None)
            if pid:
                data["ports"] = processes.listening_ports(pid)
        return {"success": True, "data": data}

    @app.get("/workspaces/{workspace_id}/processes/{name}/logs")
    def process_logs(workspace_id: str, name: str, tail: int = 200):
        check_workspace(workspace_id)
        process = registry.get(workspace_id, name)
        return {"success": True, "data": {"name": process.name, "log": processes.tail(process.log_path, tail)}}

    @app.delete("/workspaces/{workspace_id}/processes/{name}")
    async def stop_process(workspace_id: str, name: str):
        check_workspace(workspace_id)
        process = registry.get(workspace_id, name)
        await registry.stop(process)
        return {"success": True, "data": process.to_json()}

    @app.post("/workspaces/{workspace_id}/terminals")
    async def start_terminal(workspace_id: str, body: TerminalRequest):
        check_workspace(workspace_id)
        used, limit = await usage.used(settings, workspace_id), usage.limit(settings)
        # The same rule as exec: over the limit a shell can read and delete, but not write.
        full = used > limit

        async def argv_for(timeout: int, tty: str):
            return await prepare(workspace_id, terminals.COMMAND, timeout, fsize_mb=0 if full else 1024, tty=tty)

        note = usage.over_limit_message(used, limit) if full else ""
        terminal = await shells.start(workspace_id, argv_for, body.cols, body.rows, note)
        return {"success": True, "data": terminal.to_json()}

    @app.get("/workspaces/{workspace_id}/terminals")
    def list_terminals(workspace_id: str):
        check_workspace(workspace_id)
        return {"success": True, "data": {"terminals": shells.list(workspace_id)}}

    @app.delete("/workspaces/{workspace_id}/terminals/{terminal_id}")
    async def stop_terminal(workspace_id: str, terminal_id: str):
        check_workspace(workspace_id)
        await shells.stop(shells.get(workspace_id, terminal_id))
        return {"success": True, "data": {"deleted": True}}

    @app.websocket("/workspaces/{workspace_id}/terminals/{terminal_id}")
    async def attach_terminal(ws: WebSocket, workspace_id: str, terminal_id: str):
        """Output goes out as binary frames, the scrollback first. Input comes in as JSON text
        frames: {"type": "input", "data": str} or {"type": "resize", "cols": int, "rows": int}.
        Closes with 4404 for a terminal that does not exist and 1000 when the shell exits."""
        try:
            check_workspace(workspace_id)
            terminal = shells.get(workspace_id, terminal_id)
        except jail.JailError:
            await ws.close(4404)
            return
        await ws.accept()
        queue = terminal.attach()

        async def send():
            while (data := await queue.get()) is not None:
                await ws.send_bytes(data)
            await ws.close(1000, "exited" if terminal.ended.is_set() else "too slow")

        async def receive():
            while True:
                text = await ws.receive_text()
                if len(text) > TERMINAL_INPUT_MAX:
                    await ws.close(1009, "input too large")
                    return
                with contextlib.suppress(ValueError, TypeError, KeyError):
                    message = json.loads(text)
                    if message["type"] == "input" and isinstance(message["data"], str):
                        await terminal.write(message["data"].encode())
                    elif message["type"] == "resize":
                        terminal.resize(int(message["cols"]), int(message["rows"]))

        tasks_ = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            await asyncio.wait(tasks_, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks_:
                task.cancel()
            for task in tasks_:
                with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                    await task
            terminal.detach(queue)

    @app.api_route("/workspaces/{workspace_id}/ports/{port}/http/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def forward_http(workspace_id: str, request: Request, port: int = PathParam(ge=1, le=65535), path: str = ""):
        check_workspace(workspace_id)
        return await preview.forward(settings, workspace_id, port, request)

    return app


def bind_socket(path: Path, owner_uid: int) -> socket.socket:
    """Bind the socket with only its owner (the api container's user) able to connect."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old_umask = os.umask(0o177)
    try:
        sock.bind(str(path))
    finally:
        os.umask(old_umask)
    os.chown(path, owner_uid, -1)
    return sock


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = jail.load_settings()
    sock = bind_socket(Path(os.environ.get("RUNNER_SOCKET", "/run/echo/runner.sock")), int(os.environ.get("RUNNER_API_UID", "10001")))
    uvicorn.run(create_app(settings), fd=sock.fileno(), log_level="info")


if __name__ == "__main__":
    main()
