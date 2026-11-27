"""The user's terminals in an agent's workspace. The shell runs in the runner; the socket here only
copies frames between the browser and the runner, after checking who is asking."""

import asyncio
import contextlib
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import async_sessionmaker
from websockets.exceptions import ConnectionClosed, InvalidStatus

from apps.accounts.services import session_service
from apps.agents.routers.agent_router import OwnedAgent
from apps.credentials.models.credential import Deleted
from apps.agents.services import agent_service
from apps.terminal.models.terminal import NewTerminal, Terminal, Terminals
from core.auth import current_user
from core.config import get_settings
from core.errors import AppError
from sandbox import terminals

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", dependencies=[Depends(current_user)], tags=["terminals"])
# The socket signs the user in itself, so that a refusal is a close code the page can act on
# rather than a failed handshake it cannot tell from a network error.
socket_router = APIRouter(prefix="/api/agents")

# Close codes the page acts on. 1000 means the shell exited.
NOT_SIGNED_IN = 4401
NOT_FOUND = 4404
RUNNER_DOWN = 1011


@router.post("/{agent_id}/terminals", summary="Open a shell in the agent's workspace")
async def start_terminal(agent_id: OwnedAgent, body: NewTerminal) -> Terminal:
    return Terminal(**await terminals.start(get_settings().runner_socket, agent_id, body.cols, body.rows))


@router.get("/{agent_id}/terminals", summary="List the shells open in the agent's workspace")
async def list_terminals(agent_id: OwnedAgent) -> Terminals:
    return Terminals(terminals=await terminals.list_all(get_settings().runner_socket, agent_id))


@router.delete("/{agent_id}/terminals/{terminal_id}", summary="End a shell")
async def stop_terminal(agent_id: OwnedAgent, terminal_id: str) -> Deleted:
    await terminals.stop(get_settings().runner_socket, agent_id, terminal_id)
    return Deleted(deleted=True)


async def _owner_check(ws: WebSocket, agent_id: str) -> int | None:
    """None when the signed-in user owns the agent, else the close code to send. The database
    session is closed before the socket starts, which may stay open for hours."""
    async with async_sessionmaker(ws.app.state.db_engine, expire_on_commit=False)() as session:
        user = await session_service.user_for(session, ws.cookies.get(session_service.COOKIE))
        if user is None:
            return NOT_SIGNED_IN
        try:
            await agent_service.require_agent(session, user.id, agent_id)
        except AppError:
            return NOT_FOUND
    return None


@socket_router.websocket("/{agent_id}/terminals/{terminal_id}")
async def attach_terminal(ws: WebSocket, agent_id: str, terminal_id: str):
    """Binary frames out are terminal output; text frames in are the runner's JSON messages
    ({"type": "input", "data"} and {"type": "resize", "cols", "rows"}), passed on unread."""
    refusal = await _owner_check(ws, agent_id)
    await ws.accept()
    if refusal is not None:
        await ws.close(refusal)
        return
    try:
        async with terminals.connect(get_settings().runner_socket, agent_id, terminal_id) as runner:
            await _copy(ws, runner)
    except (AppError, InvalidStatus):
        # A bad id, or the runner refused the handshake: the terminal is not there.
        await _close(ws, NOT_FOUND)
    except (OSError, TimeoutError) as exc:
        logger.warning("Terminal socket to the runner failed: %s", exc)
        await _close(ws, RUNNER_DOWN)


async def _copy(ws: WebSocket, runner) -> None:
    async def to_runner():
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("text") is not None:
                await runner.send(message["text"])

    async def to_browser():
        with contextlib.suppress(ConnectionClosed):
            async for frame in runner:
                if isinstance(frame, bytes):
                    await ws.send_bytes(frame)

    tasks = [asyncio.create_task(to_runner()), asyncio.create_task(to_browser())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, ConnectionClosed, RuntimeError):
                await task
    if tasks[1] in done:
        # The runner ended it: pass on why (1000 when the shell exited, 4404 when it was gone).
        await _close(ws, runner.close_code or 1000, runner.close_reason or "")


async def _close(ws: WebSocket, code: int, reason: str = "") -> None:
    with contextlib.suppress(RuntimeError, WebSocketDisconnect):
        await ws.close(code, reason)
