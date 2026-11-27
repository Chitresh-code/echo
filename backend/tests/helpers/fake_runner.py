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
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse


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
        # Processes by workspace and name, the ports every list reports, each process's log, and
        # the process calls received as (method, workspace, name or None, body or query).
        self.processes: dict[str, dict[str, dict]] = {}
        self.ports: list[int] = []
        self.process_log = ""
        self.process_calls: list[tuple] = []
        # Requests the preview route received, as dicts, and what it answers: status, raw headers, body.
        self.previews: list[dict] = []
        self.preview_answer: tuple[int, list[tuple[str, str]], bytes] = (200, [("content-type", "text/html")], b"<p>hello</p>")
        # Terminals by workspace, and every text frame a terminal socket received. A socket sends
        # b"replay" first, answers each frame with b"got:" + the frame, and closes with 1000 on
        # the frame "exit".
        self.terminals: dict[str, list[dict]] = {}
        self.terminal_frames: list[str] = []
        # Local MCP servers: each start runs its command for real (tests give a Python script), the
        # start requests as received, every message sent to a server, and the sessions deleted.
        self.mcp: dict[str, asyncio.subprocess.Process] = {}
        self.mcp_starts: list[dict] = []
        self.mcp_sent: list[dict] = []
        self.mcp_deleted: list[str] = []

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

        def no_process(name):
            return JSONResponse(status_code=404, content={"success": False, "error": {"code": "process_not_found", "message": f"There is no process named {name}.", "details": None}})

        @app.post("/workspaces/{workspace_id}/processes")
        async def start_process(workspace_id: str, request: Request):
            body = await request.json()
            self.process_calls.append(("POST", workspace_id, None, body))
            if self.error:
                return JSONResponse(status_code=self.error[0], content=self.error[1])
            process = {"name": body["name"], "command": body["command"], "cwd": body.get("cwd"), "status": "running", "exit_code": None, "started_at": 1.0}
            self.processes.setdefault(workspace_id, {})[body["name"]] = process
            return {"success": True, "data": process}

        @app.get("/workspaces/{workspace_id}/processes")
        def list_processes(workspace_id: str):
            self.process_calls.append(("GET", workspace_id, None, None))
            return {"success": True, "data": {"processes": list(self.processes.get(workspace_id, {}).values()), "ports": self.ports}}

        @app.get("/workspaces/{workspace_id}/processes/{name}/logs")
        def process_logs(workspace_id: str, name: str, tail: int = 200):
            self.process_calls.append(("logs", workspace_id, name, tail))
            if name not in self.processes.get(workspace_id, {}):
                return no_process(name)
            return {"success": True, "data": {"name": name, "log": self.process_log}}

        @app.delete("/workspaces/{workspace_id}/processes/{name}")
        def stop_process(workspace_id: str, name: str):
            self.process_calls.append(("DELETE", workspace_id, name, None))
            process = self.processes.get(workspace_id, {}).get(name)
            if process is None:
                return no_process(name)
            process.update(status="exited", exit_code=143)
            return {"success": True, "data": process}

        @app.api_route("/workspaces/{workspace_id}/ports/{port}/http/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
        async def preview(workspace_id: str, port: int, path: str, request: Request):
            self.previews.append({
                "method": request.method, "workspace_id": workspace_id, "port": port, "raw_path": request.scope["raw_path"],
                "query": request.scope["query_string"], "headers": request.headers.raw, "body": await request.body(),
            })
            status, headers, body = self.preview_answer
            response = Response(body, status)
            response.raw_headers = [(k.encode(), v.encode()) for k, v in headers] + [(b"content-length", str(len(body)).encode())]
            return response

        @app.post("/workspaces/{workspace_id}/terminals")
        async def start_terminal(workspace_id: str, request: Request):
            self.requests.append({"workspace_id": workspace_id, "terminal": await request.json()})
            terminal = {"id": f"{len(self.terminals.get(workspace_id, [])) + 1:032x}", "started_at": 1.0, "attached": 0}
            self.terminals.setdefault(workspace_id, []).append(terminal)
            return {"success": True, "data": terminal}

        @app.get("/workspaces/{workspace_id}/terminals")
        def list_terminals(workspace_id: str):
            return {"success": True, "data": {"terminals": self.terminals.get(workspace_id, [])}}

        @app.delete("/workspaces/{workspace_id}/terminals/{terminal_id}")
        def stop_terminal(workspace_id: str, terminal_id: str):
            before = self.terminals.get(workspace_id, [])
            self.terminals[workspace_id] = [t for t in before if t["id"] != terminal_id]
            if len(before) == len(self.terminals[workspace_id]):
                return JSONResponse(status_code=404, content={"success": False, "error": {"code": "terminal_not_found", "message": "There is no terminal with this id. It may have ended.", "details": None}})
            return {"success": True, "data": {"deleted": True}}

        @app.websocket("/workspaces/{workspace_id}/terminals/{terminal_id}")
        async def attach_terminal(ws: WebSocket, workspace_id: str, terminal_id: str):
            if terminal_id not in [t["id"] for t in self.terminals.get(workspace_id, [])]:
                await ws.close(4404)
                return
            await ws.accept()
            await ws.send_bytes(b"replay")
            try:
                while True:
                    text = await ws.receive_text()
                    self.terminal_frames.append(text)
                    if text == "exit":
                        await ws.close(1000, "exited")
                        return
                    await ws.send_bytes(b"got:" + text.encode())
            except WebSocketDisconnect:
                self.closed.set()

        def no_session():
            return JSONResponse(status_code=404, content={"success": False, "error": {"code": "mcp_session_not_found", "message": "There is no MCP session with this id.", "details": None}})

        @app.post("/workspaces/{workspace_id}/mcp")
        async def start_mcp(workspace_id: str, request: Request):
            body = await request.json()
            self.mcp_starts.append({"workspace_id": workspace_id, **body})
            if self.error:
                return JSONResponse(status_code=self.error[0], content=self.error[1])
            proc = await asyncio.create_subprocess_exec(
                body["command"], *body["args"], stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            session_id = f"{len(self.mcp_starts):032x}"
            self.mcp[session_id] = proc
            return {"success": True, "data": {"id": session_id}}

        @app.get("/workspaces/{workspace_id}/mcp/{session_id}/messages")
        async def mcp_messages(workspace_id: str, session_id: str):
            proc = self.mcp.get(session_id)
            if proc is None:
                return no_session()

            async def stream():
                try:
                    while line := await proc.stdout.readline():
                        yield (json.dumps({"message": json.loads(line)}) + "\n").encode()
                    code = await proc.wait()
                    yield (json.dumps({"exit": code, "stderr": (await proc.stderr.read()).decode()[-2000:]}) + "\n").encode()
                finally:
                    if proc.returncode is None:
                        proc.kill()
                        await proc.wait()
                    self.mcp.pop(session_id, None)
                    self.closed.set()

            return StreamingResponse(stream(), media_type="application/x-ndjson")

        @app.post("/workspaces/{workspace_id}/mcp/{session_id}/messages")
        async def mcp_send(workspace_id: str, session_id: str, request: Request):
            proc = self.mcp.get(session_id)
            if proc is None:
                return no_session()
            message = await request.json()
            self.mcp_sent.append(message)
            if proc.returncode is not None:
                return JSONResponse(status_code=409, content={"success": False, "error": {"code": "mcp_session_ended", "message": "The MCP server has exited.", "details": None}})
            proc.stdin.write(json.dumps(message).encode() + b"\n")
            await proc.stdin.drain()
            return {"success": True, "data": {"sent": True}}

        @app.delete("/workspaces/{workspace_id}/mcp/{session_id}")
        async def stop_mcp(workspace_id: str, session_id: str):
            self.mcp_deleted.append(session_id)
            proc = self.mcp.pop(session_id, None)
            if proc is None:
                return no_session()
            if proc.returncode is None:
                proc.kill()
            return {"success": True, "data": {"deleted": True}}

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
