"""A stand-in for the runner on a temporary Unix socket, so the api's runner client is tested over
a real connection without nsjail. Tests set what the next exec returns and read what it received."""

import asyncio
import json
import shutil
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


class FakeRunner:
    def __init__(self):
        # Short directory under /tmp: macOS limits Unix socket paths to about 100 bytes.
        self._dir = tempfile.mkdtemp(dir="/tmp", prefix="echo-fr-")
        self.socket_path = Path(self._dir) / "runner.sock"
        self.reset()
        self._server = uvicorn.Server(uvicorn.Config(self._app(), uds=str(self.socket_path), log_level="warning"))
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def reset(self):
        # What each exec streams back. `queue` holds per-call answers in order; once it is empty
        # every call gets `lines`.
        self.lines: list[dict] = []
        self.queue: list[list[dict]] = []
        self.error: tuple[int, dict] | None = None
        # True holds every exec open after its lines; a string holds commands containing it before
        # any output.
        self.hold: bool | str = False
        self.requests: list[dict] = []
        self.closed = threading.Event()
        self.workspaces: list[str] = []
        self.deleted: list[str] = []
        # What GET /workspaces/{id}/usage answers.
        self.usage = {"used_bytes": 1024, "limit_bytes": 2048 * 1024 * 1024}

    def _app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/health")
        def health():
            return {"success": True, "data": {"status": "ok"}}

        @app.post("/workspaces/{workspace_id}")
        def create_workspace(workspace_id: str):
            self.workspaces.insert(0, workspace_id)
            return {"success": True, "data": {"id": workspace_id}}

        @app.delete("/workspaces/{workspace_id}")
        def delete_workspace(workspace_id: str):
            self.deleted.append(workspace_id)
            return {"success": True, "data": {"deleted": True}}

        @app.get("/workspaces/{workspace_id}/usage")
        def workspace_usage(workspace_id: str):
            return {"success": True, "data": self.usage}

        @app.get("/workspaces")
        def list_workspaces():
            return {"success": True, "data": self.workspaces}

        @app.post("/workspaces/{workspace_id}/exec")
        async def exec_command(workspace_id: str, request: Request):
            body = await request.json()
            self.requests.append({"workspace_id": workspace_id, **body})
            if self.error:
                status, body = self.error
                return JSONResponse(status_code=status, content=body)

            lines = self.queue.pop(0) if self.queue else self.lines

            async def stream():
                try:
                    # A held command never finishes, like one still running in its jail.
                    while isinstance(self.hold, str) and self.hold in body["command"]:
                        await asyncio.sleep(0.01)
                    for line in lines:
                        yield (json.dumps(line) + "\n").encode()
                    while self.hold is True:
                        await asyncio.sleep(0.01)
                finally:
                    self.closed.set()

            return StreamingResponse(stream(), media_type="application/x-ndjson")

        return app

    def start(self):
        self._thread.start()
        deadline = time.monotonic() + 5
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("fake runner did not start")
            time.sleep(0.01)

    def stop(self):
        self._server.should_exit = True
        self._thread.join(5)
        shutil.rmtree(self._dir, ignore_errors=True)
