"""Reports what the agent's subagents do to the turn's stream, and gives them Echo's rules.

The harness runs each `subagent` call as a background task with a fresh child agent, so the child's
events never reach the turn's stream, and the child gets the harness's generic role prompt instead
of Echo's instructions. The harness passes the agent's hooks on to every child, so this one hook
sees the parent and its children. It may be called from the background runtime's thread, so it
only hands finished SSE strings to `emit`, which must be thread safe."""

import threading
from collections.abc import Callable

from strands import Agent
from strands.hooks import AfterInvocationEvent, AfterToolCallEvent, BeforeInvocationEvent, BeforeToolCallEvent, HookProvider, HookRegistry

from apps.chat.services.sse import USAGE_KEYS, detail, message

SUBAGENT = "subagent"


class Delegation(HookProvider):
    def __init__(self, emit: Callable[[str], None]):
        self.emit = emit
        # Set by the agent factory: the turn's own agent, and the rules every child gets.
        self.parent: Agent | None = None
        self.rules = ""
        self._lock = threading.Lock()
        # Subagent tool use id to its task, for calls no child has claimed yet.
        self._pending: dict[str, str] = {}
        # Child agent to the tool use id that started it. Holding the agent keeps its identity unique.
        self._children: dict[Agent, str] = {}
        # Each child's latest usage, which is cumulative across its invocations.
        self._usage: dict[Agent, dict] = {}

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeInvocationEvent, self._started)
        registry.add_callback(BeforeToolCallEvent, self._tool_started)
        registry.add_callback(AfterToolCallEvent, self._tool_finished)
        registry.add_callback(AfterInvocationEvent, self._finished)

    def total_usage(self) -> dict[str, int]:
        with self._lock:
            return {key: sum(u.get(key, 0) for u in self._usage.values()) for key in USAGE_KEYS}

    def _started(self, event: BeforeInvocationEvent) -> None:
        child = event.agent
        if child is self.parent:
            return
        with self._lock:
            if child in self._children:
                return  # resumed to receive its own background results
            call_id = self._claim(_last_text(event.messages))
            self._children[child] = call_id
        child.system_prompt = f"{child.system_prompt}\n\n{self.rules}"
        self.emit(message("delegate", {"id": call_id, "task": self._task_of(call_id)}))

    def _claim(self, prompt: str) -> str:
        """The pending call whose task the child's prompt ends with: the harness puts the task last
        whatever context it shares. Else the oldest unclaimed one."""
        claimed = set(self._children.values())
        unclaimed = [(i, t) for i, t in self._pending.items() if i not in claimed]
        match = next((i for i, t in unclaimed if t and prompt.rstrip().endswith(t.rstrip())), None)
        return match or (unclaimed[0][0] if unclaimed else "")

    def _task_of(self, call_id: str) -> str:
        return self._pending.get(call_id, "")[:300]

    def _tool_started(self, event: BeforeToolCallEvent) -> None:
        use = event.tool_use
        if event.agent is self.parent:
            if use.get("name") == SUBAGENT:
                task = use.get("input", {}).get("task") if isinstance(use.get("input"), dict) else None
                with self._lock:
                    self._pending[use["toolUseId"]] = task if isinstance(task, str) else ""
            return
        if (call_id := self._call_of(event.agent)) is not None:
            self.emit(message("delegate_tool", {"delegate": call_id, "id": use["toolUseId"], "name": use.get("name"), "detail": detail(use.get("input"))}))

    def _tool_finished(self, event: AfterToolCallEvent) -> None:
        use, ok = event.tool_use, event.result.get("status") == "success"
        if event.agent is self.parent:
            # Fires with the child's real result; the "dispatched" acknowledgement fires no hook.
            if use.get("name") == SUBAGENT:
                self.emit(message("delegate_done", {"id": use["toolUseId"], "ok": ok}))
            return
        if (call_id := self._call_of(event.agent)) is not None:
            self.emit(message("delegate_tool_result", {"delegate": call_id, "id": use["toolUseId"], "ok": ok}))

    def _finished(self, event: AfterInvocationEvent) -> None:
        if event.agent is self.parent or event.result is None:
            return
        with self._lock:
            self._usage[event.agent] = dict(event.result.metrics.accumulated_usage)

    def task_for(self, child: Agent) -> str | None:
        """The task of the subagent call that started `child`, or None when it is not a child."""
        call_id = self._call_of(child)
        return None if call_id is None else self._task_of(call_id)

    def _call_of(self, child: Agent) -> str | None:
        with self._lock:
            return self._children.get(child)


def _last_text(messages) -> str:
    for block in reversed((messages or [{}])[-1].get("content", []) if messages else []):
        if isinstance(block.get("text"), str):
            return block["text"]
    return ""
