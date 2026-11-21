"""The runner: the only process that starts jails. It listens on a Unix socket that only the api
container's user can open, and no network port, so neither a jail nor anything on the network
can ask it to run a command."""

import json
import logging
import os
import shutil
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import jail

logger = logging.getLogger("runner")


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
    app = FastAPI(title="Echo runner", docs_url=None, redoc_url=None, openapi_url=None)
    # Command files are removed after each run; clearing the directory at startup removes any
    # left by a crash.
    shutil.rmtree(jail.commands_dir(settings), ignore_errors=True)
    jail.commands_dir(settings).mkdir(parents=True)

    @app.exception_handler(jail.JailError)
    async def jail_error(request: Request, exc: jail.JailError):
        return _error(400, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return _error(422, "validation_error", "The request is not valid.")

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        logger.error("Unhandled exception", exc_info=exc)
        return _error(500, "runner_error", "The runner failed.")

    def prepare(workspace_id: str, command: str, timeout: int, cwd=None, env=None) -> tuple[list[str], Path]:
        script = jail.write_script(settings, command)
        try:
            return jail.build_argv(settings, workspace_id, script, timeout, cwd, env), script
        except BaseException:
            script.unlink()
            raise

    async def run_to_end(workspace_id: str, command: str) -> jail.Exit:
        argv, script = prepare(workspace_id, command, 60)
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

    @app.post("/workspaces/{workspace_id}/exec")
    async def exec_command(workspace_id: str, body: ExecRequest):
        if not jail.workspace_dir(settings, workspace_id).is_dir():
            return _error(404, "workspace_not_found", "There is no workspace with this id.")
        timeout = jail.effective_timeout(settings, body.timeout)
        # Built before the response starts, so a bad request is a 400, not a broken stream.
        argv, script = prepare(workspace_id, body.command, timeout, body.cwd, body.env)

        async def lines() -> AsyncIterator[bytes]:
            # When the client disconnects, Starlette cancels this generator, and closing jail.run
            # kills the jail.
            try:
                async for item in jail.run(argv, timeout):
                    if isinstance(item, jail.Exit):
                        line = {"exit_code": item.exit_code, "timed_out": item.timed_out}
                    else:
                        line = {"stream": item.stream, "data": item.data}
                    yield (json.dumps(line) + "\n").encode()
            finally:
                script.unlink(missing_ok=True)

        return StreamingResponse(lines(), media_type="application/x-ndjson")

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
