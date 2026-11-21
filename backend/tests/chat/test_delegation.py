import json
import threading
from types import SimpleNamespace as NS

from apps.chat.services.delegation import Delegation


class FakeAgent:
    def __init__(self):
        self.system_prompt = "generic role"


def events(sent: list[str]) -> list[tuple[str, dict]]:
    out = []
    for sse in sent:
        head, data = sse.strip().split("\n")
        out.append((head.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def setup():
    sent = []
    hook = Delegation(sent.append)
    hook.parent, hook.rules = FakeAgent(), "# Untrusted content\nrules"
    return hook, sent


def call(hook, agent, tool_id, name, tool_input=None, status=None):
    use = {"toolUseId": tool_id, "name": name, "input": tool_input or {}}
    if status is None:
        hook._tool_started(NS(agent=agent, tool_use=use))
    else:
        hook._tool_finished(NS(agent=agent, tool_use=use, result={"status": status}))


def start(hook, child, text):
    hook._started(NS(agent=child, messages=[{"role": "user", "content": [{"text": text}]}]))


def finish(hook, child, usage):
    hook._finished(NS(agent=child, result=NS(metrics=NS(accumulated_usage=usage))))


def test_children_are_tied_to_their_calls_and_reported():
    hook, sent = setup()
    call(hook, hook.parent, "p1", "subagent", {"task": "Find the TODOs"})
    call(hook, hook.parent, "p2", "subagent", {"task": "List the scripts"})
    call(hook, hook.parent, "p3", "shell", {"command": "ls"})  # the parent's own tools are streamed elsewhere
    a, b = FakeAgent(), FakeAgent()
    # Started in reverse order, and b's prompt carries shared context before its task.
    start(hook, b, "<parent_context>...</parent_context>\n\nList the scripts")
    start(hook, a, "Find the TODOs")
    call(hook, a, "c1", "shell", {"command": "grep -rn TODO ."})
    call(hook, a, "c1", "shell", {"command": "grep -rn TODO ."}, status="error")
    call(hook, hook.parent, "p1", "subagent", status="success")
    call(hook, hook.parent, "p2", "subagent", status="error")
    assert events(sent) == [
        ("delegate", {"id": "p2", "task": "List the scripts"}),
        ("delegate", {"id": "p1", "task": "Find the TODOs"}),
        ("delegate_tool", {"delegate": "p1", "id": "c1", "name": "shell", "detail": "grep -rn TODO ."}),
        ("delegate_tool_result", {"delegate": "p1", "id": "c1", "ok": False}),
        ("delegate_done", {"id": "p1", "ok": True}),
        ("delegate_done", {"id": "p2", "ok": False}),
    ]


def test_rules_are_added_once_and_a_resume_reports_nothing():
    hook, sent = setup()
    call(hook, hook.parent, "p1", "subagent", {"task": "Do it"})
    child = FakeAgent()
    start(hook, child, "Do it")
    start(hook, child, "")  # the harness resumes a child to hand it its own background results
    assert child.system_prompt == "generic role\n\n# Untrusted content\nrules"
    assert [name for name, _ in events(sent)] == ["delegate"]


def test_an_unmatched_child_takes_the_oldest_unclaimed_call():
    hook, sent = setup()
    call(hook, hook.parent, "p1", "subagent", {"task": "one"})
    call(hook, hook.parent, "p2", "subagent", {"task": "two"})
    start(hook, FakeAgent(), "something else")
    assert events(sent) == [("delegate", {"id": "p1", "task": "one"})]


def test_the_parent_is_never_reported_or_changed():
    hook, sent = setup()
    start(hook, hook.parent, "hello")
    finish(hook, hook.parent, {"inputTokens": 999})
    assert sent == [] and hook.parent.system_prompt == "generic role" and hook.total_usage()["inputTokens"] == 0


def test_usage_keeps_each_childs_latest_total():
    hook, _ = setup()
    a, b = FakeAgent(), FakeAgent()
    finish(hook, a, {"inputTokens": 30, "outputTokens": 3})
    finish(hook, a, {"inputTokens": 40, "outputTokens": 4})  # cumulative across a resume
    finish(hook, b, {"inputTokens": 10, "outputTokens": 1, "cacheReadInputTokens": 5})
    hook._finished(NS(agent=b, result=None))
    assert hook.total_usage() == {"inputTokens": 50, "outputTokens": 5, "cacheReadInputTokens": 5, "cacheWriteInputTokens": 0}


def test_hooks_from_another_thread_reach_emit():
    hook, sent = setup()
    call(hook, hook.parent, "p1", "subagent", {"task": "t"})
    child = FakeAgent()
    thread = threading.Thread(target=lambda: (start(hook, child, "t"), call(hook, child, "c1", "read", {"path": "a.py"})))
    thread.start()
    thread.join()
    assert [name for name, _ in events(sent)] == ["delegate", "delegate_tool"]
