"""Asks the user before a tool that can change something or reach outside the workspace runs.

One gate per turn, handed to the harness as an intervention, which gives the same instance to every
`subagent` child, so a delegate cannot get around it. Children run on the harness's background
thread with their own event loop, so a waiting call holds a thread-safe future and every event goes
out through `emit`, which must be thread safe. The cards are ordinary turn events: a page that
attaches to the turn later replays them, and a card with no `approval_done` after it can still be
answered from any tab of the signed-in owner."""

import asyncio
import concurrent.futures
import json
import logging
import secrets
import threading
import time
from collections.abc import Callable
from typing import Literal

from strands import Agent
from strands.interventions import Deny, InterventionHandler, Proceed

from apps.chat.services.delegation import Delegation
from apps.chat.services.sse import message

logger = logging.getLogger(__name__)

Mode = Literal["ask", "yolo"]
Decision = Literal["allow", "deny", "always"]

# Tools that only read the workspace or the agent's own notes, keep its plan, or start a subagent
# whose own calls pass through this gate.
FREE = frozenset({"read", "skills", "search_memory", "retrieve_context", "todo_write", "subagent", "strands_manage_background_task"})
# How long a card waits for an answer before the call is denied.
WAIT_SECONDS = 600
# The input shown on a card; the call itself still gets all of it.
MAX_SHOWN_INPUT = 20_000
# Saved with the chat's session, so "Allow for this chat" holds in its later turns and nowhere else.
TRUSTED_KEY = "echo_trusted_tools"
DENIED = "The user denied this call. Ask them what they want instead of trying it again."
TIMED_OUT = "No one answered the approval request in 10 minutes, so the call was not run."

_lock = threading.Lock()
# Approval id to the gate waiting on it, so an answer finds its call.
_pending: dict[str, "Approvals"] = {}
# Every live turn's gate, so a mode change reaches turns already running.
# shortcut: in memory, so it only holds with one api worker, like the turn's busy set; move both when the api runs more than one.
_gates: set["Approvals"] = set()


class Approvals(InterventionHandler):
    name = "echo-approvals"

    def __init__(self, agent_id: str, user_id: str, mode: Mode, emit: Callable[[str], None], delegation: Delegation | None = None):
        self.agent_id, self.user_id, self.mode, self.emit, self.delegation = agent_id, user_id, mode, emit, delegation
        # Set by the agent factory: the turn's own agent, whose state keeps the chat's trusted tools.
        self.parent: Agent | None = None
        # Moves the turn's deadline by this many seconds; set by the turn so a wait does not use up its time.
        self.extend: Callable[[float], None] = lambda seconds: None
        # Set by the turn: MCP tool name to its server and the hints the server claims, for the card.
        self.mcp_tools: dict[str, dict] = {}
        self._waiting: dict[str, concurrent.futures.Future] = {}
        with _lock:
            _gates.add(self)

    @property
    def on_error(self):
        # A broken gate must not let a call through.
        return "deny"

    async def before_tool_call(self, event, **kwargs):
        use = event.tool_use
        tool = use.get("name") or ""
        if self.mode == "yolo" or tool in FREE or tool in self._trusted():
            return Proceed()
        approval_id = secrets.token_urlsafe(16)
        future: concurrent.futures.Future = concurrent.futures.Future()
        with _lock:
            _pending[approval_id] = self
            self._waiting[approval_id] = future
        self.emit(message("approval_needed", self._card(approval_id, tool, use.get("input"), event.agent)))
        # Pushed back for the whole wait now and given back after, so the deadline cannot pass mid-wait.
        self.extend(WAIT_SECONDS)
        started = time.monotonic()
        decision = "deny"
        try:
            decision = await asyncio.wait_for(asyncio.wrap_future(future), WAIT_SECONDS)
        except TimeoutError:
            decision = "timeout"
        finally:
            self.extend(time.monotonic() - started - WAIT_SECONDS)
            with _lock:
                _pending.pop(approval_id, None)
                self._waiting.pop(approval_id, None)
            self.emit(message("approval_done", {"id": approval_id, "decision": decision}))
        if decision == "always":
            self._trust(tool)
        if decision in ("allow", "always"):
            return Proceed()
        return Deny(reason=TIMED_OUT if decision == "timeout" else DENIED)

    def _card(self, approval_id: str, tool: str, tool_input, agent: Agent) -> dict:
        shown = json.dumps(tool_input, ensure_ascii=False, default=str)
        mcp = self.mcp_tools.get(tool, {})
        card = {"id": approval_id, "tool": tool, "server": mcp.get("server"), "hints": mcp.get("hints"), "subagent": None, "input": tool_input}
        if len(shown) > MAX_SHOWN_INPUT:
            card["input"], card["input_cut"] = shown[:MAX_SHOWN_INPUT], True
        if self.delegation and agent is not self.parent:
            card["subagent"] = self.delegation.task_for(agent)
        return card

    def _trusted(self) -> list:
        trusted = self.parent.state.get(TRUSTED_KEY) if self.parent else None
        return trusted if isinstance(trusted, list) else []

    def _trust(self, tool: str) -> None:
        # On the turn's own agent, so a subagent's "always" also counts for the chat.
        if self.parent is None:
            return
        with _lock:
            trusted = self._trusted()
            if tool not in trusted:
                self.parent.state.set(TRUSTED_KEY, [*trusted, tool])

    def resolve(self, approval_id: str, decision: str) -> bool:
        with _lock:
            future = self._waiting.get(approval_id)
        if future is None or future.done():
            return False
        try:
            future.set_result(decision)
        except concurrent.futures.InvalidStateError:
            return False
        return True

    def deny_all(self) -> None:
        """Answers every waiting card as denied, as when the turn is stopped."""
        with _lock:
            waiting = list(self._waiting)
        for approval_id in waiting:
            self.resolve(approval_id, "deny")

    def close(self) -> None:
        self.deny_all()
        with _lock:
            _gates.discard(self)


def answer(approval_id: str, agent_id: str, user_id: str, decision: Decision) -> bool:
    """Resolves a waiting call only for the user and agent whose turn asked. False when nothing of
    theirs waits under that id, so a missing, answered or someone else's id read the same."""
    with _lock:
        gate = _pending.get(approval_id)
    if gate is None or gate.user_id != user_id or gate.agent_id != agent_id:
        return False
    return gate.resolve(approval_id, decision)


def set_mode(agent_id: str, mode: Mode) -> None:
    """Applies a mode change to the agent's running turns; switching to yolo lets waiting calls run."""
    with _lock:
        gates = [g for g in _gates if g.agent_id == agent_id]
    for gate in gates:
        gate.mode = mode
        if mode == "yolo":
            with _lock:
                waiting = list(gate._waiting)
            for approval_id in waiting:
                gate.resolve(approval_id, "allow")
