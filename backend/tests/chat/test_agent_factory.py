import builtins
import os

from apps.chat.services import agent_factory
from apps.chat.services.delegation import Delegation
from apps.credentials.services import providers
from core.config import get_settings
from sandbox.runner_sandbox import RunnerSandbox

WS, CHAT = "a" * 32, "b" * 32


def test_build_agent(monkeypatch):
    calls = []
    real = agent_factory.create_harness
    monkeypatch.setattr(agent_factory, "create_harness", lambda **kw: calls.append(kw) or real(**kw))
    settings = get_settings()

    side = providers.build_side_model("anthropic", "test-key", None, None)
    delegation = Delegation(lambda sse: None)
    agent = agent_factory.build_agent(
        settings, WS, CHAT, providers.build_model("anthropic", "test-key", None, "claude-sonnet-5-5"), "anthropic/claude-sonnet-5-5", side, "Payouts", "Reconcile weekly payouts", delegation=delegation
    )

    kw = calls[0]
    assert isinstance(agent.sandbox, RunnerSandbox) and agent.sandbox.workspace_id == WS
    assert kw["session"] == {"id": CHAT, "dir": str(settings.data_dir / "sessions" / WS)}
    assert kw["memory"] == {"dir": str(settings.data_dir / "memory" / WS)}
    assert kw["skills"] == [f"/data/workspaces/{WS}/.agent/skills"]
    assert kw["builtin_tools"]["web_fetch"] == {"transport": "curl", "model": side}
    # No programmatic_tool_caller, which would run model-written Python in the api process.
    assert sorted(agent.tool_names) == sorted([
        "shell", "read", "write", "edit", "web_fetch", "skills", "search_memory", "retrieve_context", "strands_manage_background_task",
        "subagent", "todo_write", "process",
    ])
    # Subagents cannot delegate again, at most two run at once, and no other tool goes to the background.
    assert kw["builtin_tools"]["subagent"] == {"max_depth": 1}
    assert kw["background_tasks"] == {"agentic": [], "max_concurrency": 2, "timeout": settings.turn_timeout}
    assert kw["hooks"] == [delegation] and delegation.parent is agent
    assert "# Untrusted content" in delegation.rules and f"/data/workspaces/{WS}" in delegation.rules
    assert "# Delegating and planning" in agent.system_prompt and "# Delegating" not in delegation.rules
    shell = agent.tool_registry.registry["shell"].tool_spec
    assert shell["inputSchema"]["json"]["properties"]["timeout"]["default"] == settings.command_timeout
    assert f"at most {settings.command_timeout_max}" in shell["description"]
    assert f"/data/workspaces/{WS}" in agent.system_prompt
    # The limits the agent is told are the configured ones.
    assert f"{settings.command_timeout} seconds" in agent.system_prompt and f"up to {settings.command_timeout_max}" in agent.system_prompt
    assert "Untrusted content" in agent.system_prompt
    # Servers go through the process tool, and the agent and its subagents are told so.
    assert "with the process tool" in delegation.rules and "never with & or nohup" in delegation.rules
    assert "localhost and private addresses are not" not in agent.system_prompt
    assert "use the process tool" in shell["description"]
    # The harness injects AGENTS.md every turn, so the prompt does not ask for it to be read.
    assert "Read AGENTS.md" not in agent.system_prompt
    # The agent knows which one it is and the job it is learning.
    assert 'You are "Payouts"' in agent.system_prompt and "<job>\nReconcile weekly payouts\n</job>" in agent.system_prompt
    assert "# Learning the job" in agent.system_prompt and "---\n   name: <name, the same as the folder>" in agent.system_prompt


def test_instructions_without_a_job():
    prompt = agent_factory.instructions("/data/workspaces/x", get_settings(), "Untitled agent", "")
    assert "<job>" not in prompt and "has not written down your job" in prompt


def test_agent_never_touches_the_workspace_on_the_api_side(monkeypatch, fake_runner):
    """Skills and AGENTS.md live in the sandbox container. Reading them from the api's own
    filesystem would read the wrong machine, or a path an attacker planted there."""
    from tests.chat.test_turns import run_turn, shell_then_done

    touched = []
    for module, name in [(os, "stat"), (os, "lstat"), (os, "scandir"), (os, "listdir"), (builtins, "open")]:
        real = getattr(module, name)

        def spy(path=".", *a, _real=real, **kw):
            if "/data/workspaces" in str(path):
                touched.append(str(path))
            return _real(path, *a, **kw)

        monkeypatch.setattr(module, name, spy)

    events = run_turn(monkeypatch, fake_runner, shell_then_done())
    assert events[-1][0] == "done"
    assert touched == []
    assert any(".agent/skills" in r["command"] for r in fake_runner.requests)
