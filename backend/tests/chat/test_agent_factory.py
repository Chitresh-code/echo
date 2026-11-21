import builtins
import os

import pytest

from apps.chat.services import agent_factory
from core.config import get_settings
from core.errors import AppError
from sandbox.runner_sandbox import RunnerSandbox

WS, CHAT = "a" * 32, "b" * 32


def test_check_model():
    settings = get_settings()
    assert agent_factory.check_model(settings, None) == "anthropic/claude-sonnet-5-5"
    assert agent_factory.check_model(settings, "openai/gpt-5") == "openai/gpt-5"
    with pytest.raises(AppError) as err:
        agent_factory.check_model(settings, "anthropic/some-other-model")
    assert err.value.status_code == 400 and err.value.code == "unknown_model"


def test_build_agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls = []
    real = agent_factory.create_harness
    monkeypatch.setattr(agent_factory, "create_harness", lambda **kw: calls.append(kw) or real(**kw))
    settings = get_settings()

    agent = agent_factory.build_agent(settings, WS, CHAT, "anthropic/claude-sonnet-5-5")

    kw = calls[0]
    assert isinstance(agent.sandbox, RunnerSandbox) and agent.sandbox.workspace_id == WS
    assert kw["session"] == {"id": CHAT, "dir": str(settings.data_dir / "sessions" / WS)}
    assert kw["memory"] == {"dir": str(settings.data_dir / "memory" / WS)}
    assert kw["skills"] == [f"/data/workspaces/{WS}/.agent/skills"]
    assert kw["builtin_tools"]["web_fetch"] == {"transport": "curl"}
    assert "web_fetch" in agent.tool_names and "programmatic_tool_caller" not in agent.tool_names
    assert f"/data/workspaces/{WS}" in agent.system_prompt


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
