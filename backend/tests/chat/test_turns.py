import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from apps.chat.services import agent_factory, turn_service
from core.config import get_settings
from tests.helpers.scripted_model import ScriptedModel

WS, CHAT = "a" * 32, "b" * 32
TURNS = f"/api/workspaces/{WS}/chats/{CHAT}/turns"
DONE = {"exit_code": 0, "timed_out": False}


def shell_then_done(command="echo hi"):
    return ScriptedModel([[("text", "Running it."), ("tool", "shell", {"command": command})], [("text", "Done.")]])


def use_model(monkeypatch, model):
    """Build agents the real way, with the scripted model in place of a provider."""
    real = agent_factory.build_agent
    monkeypatch.setattr(agent_factory, "build_agent", lambda s, w, c, m: real(s, w, c, model))


def parse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def run_turn(monkeypatch, fake_runner, model, prompt="say hi"):
    from main import create_app

    use_model(monkeypatch, model)
    fake_runner.workspaces = [WS]
    fake_runner.lines = [DONE]
    with TestClient(create_app()) as client:
        response = client.post(TURNS, json={"prompt": prompt})
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    return parse(response.text)


def test_turn_streams_text_tools_and_done(monkeypatch, fake_runner):
    events = run_turn(monkeypatch, fake_runner, shell_then_done())
    assert [e for e, _ in events] == ["text", "tool", "text", "done"]
    assert events[1][1]["name"] == "shell" and events[-1][1] == {"stopReason": "end_turn"}
    assert any(r["command"] == "echo hi" and r["workspace_id"] == WS for r in fake_runner.requests)
    assert (get_settings().data_dir / "sessions" / WS).is_dir()


def test_second_turn_resumes_the_session(monkeypatch, fake_runner):
    model = shell_then_done()
    run_turn(monkeypatch, fake_runner, model)
    first, calls = model.message_counts[0], len(model.message_counts)
    run_turn(monkeypatch, fake_runner, model, prompt="what did you do?")
    # The first turn's prompt, tool call, tool result and answer come back with the second prompt.
    assert model.message_counts[calls] >= first + 4


def test_create_chat_and_models(client, fake_runner):
    fake_runner.workspaces = [WS]
    chat = client.post(f"/api/workspaces/{WS}/chats").json()["data"]
    assert len(chat["id"]) == 32
    assert client.get("/api/models").json()["data"] == {"models": ["anthropic/claude-sonnet-5-5", "openai/gpt-5"], "default": "anthropic/claude-sonnet-5-5"}


@pytest.mark.parametrize("url, body, status, code", [
    (TURNS, {"prompt": "hi", "model": "anthropic/not-offered"}, 400, "unknown_model"),
    (f"/api/workspaces/{WS}/chats/../turns", {"prompt": "hi"}, 404, None),
    (f"/api/workspaces/{WS}/chats/not-a-chat/turns", {"prompt": "hi"}, 400, "invalid_chat_id"),
    (f"/api/workspaces/bad/chats/{CHAT}/turns", {"prompt": "hi"}, 400, "invalid_workspace_id"),
    (TURNS, {"prompt": ""}, 422, "validation_error"),
])
def test_bad_requests_are_refused_before_any_command(client, fake_runner, url, body, status, code):
    response = client.post(url, json=body)
    assert response.status_code == status
    if code:
        assert response.json()["error"]["code"] == code
    assert fake_runner.requests == []


def test_missing_workspace_is_404(client, fake_runner):
    response = client.post(TURNS, json={"prompt": "hi"})
    assert response.status_code == 404 and response.json()["error"]["code"] == "workspace_not_found"


def test_busy_chat_is_409(client, fake_runner):
    fake_runner.workspaces = [WS]
    turn_service._busy.add(f"{WS}/{CHAT}")
    try:
        response = client.post(TURNS, json={"prompt": "hi"})
    finally:
        turn_service._busy.clear()
    assert response.status_code == 409 and response.json()["error"]["code"] == "chat_busy"


def agent_maker(model):
    return lambda: agent_factory.build_agent(get_settings(), WS, CHAT, model)


async def wait_for(condition, seconds=5):
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(0.01)


async def test_disconnect_stops_the_running_command(fake_runner):
    fake_runner.lines = [DONE]
    fake_runner.hold = "sleep 100"
    stream = turn_service.stream_turn("k1", agent_maker(shell_then_done("sleep 100")), "go", 60)
    assert (await anext(stream)).startswith("event: text")
    assert (await anext(stream)).startswith("event: tool")
    await wait_for(lambda: any(r["command"] == "sleep 100" for r in fake_runner.requests))
    fake_runner.closed.clear()
    assert turn_service.is_busy("k1")

    await stream.aclose()

    await asyncio.to_thread(fake_runner.closed.wait, 5)
    assert fake_runner.closed.is_set()
    await wait_for(lambda: not turn_service.is_busy("k1"))


async def test_turn_timeout_stops_the_turn(fake_runner):
    fake_runner.lines = [DONE]
    fake_runner.hold = "sleep 100"
    events = [e async for e in turn_service.stream_turn("k2", agent_maker(shell_then_done("sleep 100")), "go", 1)]
    assert events[-1].startswith("event: error") and "turn_timeout" in events[-1]
    await asyncio.to_thread(fake_runner.closed.wait, 5)
    await wait_for(lambda: not turn_service.is_busy("k2"))


async def test_a_racing_second_turn_gets_an_error_event(fake_runner):
    turn_service._busy.add("k3")
    try:
        events = [e async for e in turn_service.stream_turn("k3", agent_maker(shell_then_done()), "go", 60)]
    finally:
        turn_service._busy.clear()
    assert len(events) == 1 and "chat_busy" in events[0]


async def test_failure_becomes_an_error_event_without_its_text(fake_runner):
    def explode():
        raise RuntimeError("provider said: key sk-secret-123 is invalid")

    events = [e async for e in turn_service.stream_turn("k4", explode, "go", 60)]
    assert len(events) == 1 and "turn_failed" in events[0] and "sk-secret" not in events[0]
    await wait_for(lambda: not turn_service.is_busy("k4"))
