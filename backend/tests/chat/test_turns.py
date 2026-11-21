import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from apps.chat.services import agent_factory, turn_service
from core.config import get_settings
from apps.credentials.services import providers
from tests.helpers.accounts import add_key, own, sign_in_as
from tests.helpers.scripted_model import ScriptedModel

WS, CHAT = "a" * 32, "b" * 32
TURNS = f"/api/agents/{WS}/chats/{CHAT}/turns"
DONE = {"exit_code": 0, "timed_out": False}


def shell_then_done(command="echo hi"):
    return ScriptedModel([[("text", "Running it."), ("tool", "shell", {"command": command})], [("text", "Done.")]])


def use_model(monkeypatch, model) -> list[tuple]:
    """Build agents the real way, with the scripted model in place of the provider's. Returns the
    (provider, key, base_url, model, effort) each turn asked for."""
    asked = []
    real = providers.build_model

    def build(*args):
        # The real builder still runs, so its effort check applies.
        real(*args)
        asked.append(args)
        return model

    monkeypatch.setattr(providers, "build_model", build)
    # The scripted model also does the side work, as one model serves every call it is given.
    monkeypatch.setattr(providers, "build_side_model", lambda provider, key, base_url, main: main)
    return asked


def parse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def turn(prompt, credential_id, model="claude-sonnet-5-5", **extra):
    return {"prompt": prompt, "credential_id": credential_id, "model": model, **extra}


def run_turn(monkeypatch, fake_runner, model, prompt="say hi"):
    from main import create_app

    use_model(monkeypatch, model)
    fake_runner.lines = [DONE]
    with TestClient(create_app()) as client:
        user = sign_in_as(client)
        own(client, user, WS)
        response = client.post(TURNS, json=turn(prompt, add_key(client, user)))
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    return parse(response.text)


def test_turn_streams_text_tools_and_done(monkeypatch, fake_runner):
    events = run_turn(monkeypatch, fake_runner, shell_then_done())
    assert [e for e, _ in events] == ["text", "tool", "text", "tool_detail", "tool_result", "text", "text", "done"]
    assert events[2][1]["text"] == "\n\n" and events[3][1]["detail"] == "echo hi" and events[4][1]["ok"] is True
    assert events[1][1]["name"] == "shell" and events[-1][1]["stopReason"] == "end_turn"
    assert set(events[-1][1]["usage"]) == {"inputTokens", "outputTokens", "cacheReadInputTokens", "cacheWriteInputTokens"}
    assert any(r["command"] == "echo hi" and r["workspace_id"] == WS for r in fake_runner.requests)
    assert (get_settings().data_dir / "sessions" / WS).is_dir()


def test_a_turn_marks_the_agent_as_used(monkeypatch, fake_runner):
    from main import create_app

    use_model(monkeypatch, ScriptedModel([[("text", "Hi.")]]))
    fake_runner.lines = [DONE]
    with TestClient(create_app()) as client:
        user = sign_in_as(client)
        own(client, user, WS)
        assert client.get("/api/agents").json()["data"][0]["last_used_at"] is None
        client.post(TURNS, json=turn("hi", add_key(client, user)))
        assert client.get("/api/agents").json()["data"][0]["last_used_at"]


def test_second_turn_resumes_the_session(monkeypatch, fake_runner):
    model = shell_then_done()
    run_turn(monkeypatch, fake_runner, model)
    first, calls = model.message_counts[0], len(model.message_counts)
    run_turn(monkeypatch, fake_runner, model, prompt="what did you do?")
    # The first turn's prompt, tool call, tool result and answer come back with the second prompt.
    assert model.message_counts[calls] >= first + 4


def reasoning_reply():
    return ScriptedModel([[("reasoning", "hidden-reasoning", "sig-from-the-first-model"), ("text", "Hi.")]])


def two_turns(monkeypatch, client, user, fake_runner, second_model):
    model = reasoning_reply()
    use_model(monkeypatch, model)
    fake_runner.lines = [DONE]
    own(client, user, WS)
    key_id = add_key(client, user)
    for model_id in ("claude-sonnet-5-5", second_model):
        assert parse(client.post(TURNS, json=turn("hi", key_id, model_id)).text)[-1][0] == "done"
    # The second turn's conversation call, not the memory extraction the harness runs after a turn.
    conversation = [m for m in model.all_messages if m[0]["content"] == [{"text": "hi"}] and len(m) > 1]
    return str(conversation[-1])


def test_switching_model_drops_the_earlier_reasoning(monkeypatch, client, user, fake_runner):
    sent = two_turns(monkeypatch, client, user, fake_runner, "claude-opus-5-5")
    assert "Hi." in sent and "sig-from-the-first-model" not in sent and "hidden-reasoning" not in sent


def test_staying_on_the_model_keeps_the_reasoning(monkeypatch, client, user, fake_runner):
    assert "sig-from-the-first-model" in two_turns(monkeypatch, client, user, fake_runner, "claude-sonnet-5-5")


def test_create_chat(client, user, fake_runner):
    own(client, user, WS)
    chat = client.post(f"/api/agents/{WS}/chats").json()["data"]
    assert len(chat["id"]) == 32


def test_server_model_list_is_gone(client, user):
    assert client.get("/api/models").status_code == 404


def test_turn_runs_on_the_users_stored_key(monkeypatch, client, user, fake_runner):
    asked = use_model(monkeypatch, shell_then_done())
    fake_runner.lines = [DONE]
    own(client, user, WS)
    key_id = add_key(client, user, key="sk-ant-ada-own-key-1234567890")
    events = parse(client.post(TURNS, json=turn("hi", key_id, "claude-opus-5-5")).text)
    assert events[-1][0] == "done"
    assert asked == [("anthropic", "sk-ant-ada-own-key-1234567890", None, "claude-opus-5-5", "auto")]
    # The key goes to the model client only, never into a command.
    assert all("sk-ant" not in r["command"] for r in fake_runner.requests)


def test_turn_runs_at_the_chosen_effort(monkeypatch, client, user, fake_runner):
    asked = use_model(monkeypatch, shell_then_done())
    fake_runner.lines = [DONE]
    own(client, user, WS)
    events = parse(client.post(TURNS, json=turn("hi", add_key(client, user), effort="max")).text)
    assert events[-1][0] == "done" and asked[0][-1] == "max"


def test_unsupported_effort_is_400_before_the_stream(monkeypatch, client, user, fake_runner):
    use_model(monkeypatch, shell_then_done())
    own(client, user, WS)
    key_id = add_key(client, user, provider="google")
    response = client.post(TURNS, json=turn("hi", key_id, "gemini-2.5-flash", effort="max"))
    assert response.status_code == 400 and response.json()["error"]["code"] == "effort_not_supported"
    assert "low, medium, high" in response.json()["error"]["message"] and fake_runner.requests == []


def test_unknown_or_someone_elses_key_is_404_before_the_stream(monkeypatch, client, fake_runner):
    asked = use_model(monkeypatch, shell_then_done())
    bob = sign_in_as(client, "bob")
    bobs_key = add_key(client, bob)
    ada = sign_in_as(client, "ada")
    own(client, ada, WS)
    for key_id in (bobs_key, "f" * 32):
        response = client.post(TURNS, json=turn("hi", key_id))
        assert response.status_code == 404 and response.json()["error"]["code"] == "credential_not_found"
    assert asked == [] and fake_runner.requests == []


ANY_KEY = "c" * 32


@pytest.mark.parametrize("url, body, status, code", [
    (f"/api/agents/{WS}/chats/../turns", turn("hi", ANY_KEY), 404, None),
    (f"/api/agents/{WS}/chats/not-a-chat/turns", turn("hi", ANY_KEY), 400, "invalid_chat_id"),
    (f"/api/agents/bad/chats/{CHAT}/turns", turn("hi", ANY_KEY), 400, "invalid_agent_id"),
    (TURNS, turn("", ANY_KEY), 422, "validation_error"),
    (TURNS, {"prompt": "hi", "model": "claude-sonnet-5-5"}, 422, "validation_error"),
    (TURNS, turn("hi", ANY_KEY, model="has space"), 422, "validation_error"),
    (TURNS, turn("hi", ANY_KEY, effort="extreme"), 422, "validation_error"),
])
def test_bad_requests_are_refused_before_any_command(client, user, fake_runner, url, body, status, code):
    own(client, user, WS)
    response = client.post(url, json=body)
    assert response.status_code == status
    if code:
        assert response.json()["error"]["code"] == code
    assert fake_runner.requests == []


def test_missing_agent_is_404(client, fake_runner):
    response = client.post(TURNS, json=turn("hi", ANY_KEY))
    assert response.status_code == 404 and response.json()["error"]["code"] == "agent_not_found"


def test_busy_chat_is_409(client, user, fake_runner):
    own(client, user, WS)
    turn_service._busy.add(f"{WS}/{CHAT}")
    try:
        response = client.post(TURNS, json=turn("hi", ANY_KEY))
    finally:
        turn_service._busy.clear()
    assert response.status_code == 409 and response.json()["error"]["code"] == "chat_busy"


def agent_maker(model):
    return lambda delegation: agent_factory.build_agent(get_settings(), WS, CHAT, model, "anthropic/claude-sonnet-5-5", model, "Test agent", "", delegation=delegation)


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
    def explode(delegation):
        raise RuntimeError("provider said: key sk-secret-123 is invalid")

    events = [e async for e in turn_service.stream_turn("k4", explode, "go", 60)]
    assert len(events) == 1 and "turn_failed" in events[0] and "sk-secret" not in events[0]
    await wait_for(lambda: not turn_service.is_busy("k4"))


def hashes_in_turn(monkeypatch, *answers):
    """skill_hashes answers in order: before the turn, then after it. An exception is raised."""
    from apps.agents.services import knowledge_service

    queue = list(answers)

    async def fake(settings, agent_id):
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(knowledge_service, "skill_hashes", fake)
    return queue


def test_done_lists_the_skills_the_turn_changed(monkeypatch, fake_runner):
    before = {".agent/skills/report/SKILL.md": "a", ".agent/skills/old/SKILL.md": "b", ".agent/skills/same/SKILL.md": "c"}
    after = {".agent/skills/report/SKILL.md": "a2", ".agent/skills/same/SKILL.md": "c", ".agent/skills/new/run.py": "d"}
    left = hashes_in_turn(monkeypatch, before, after)
    events = run_turn(monkeypatch, fake_runner, shell_then_done())
    assert events[-1][0] == "done" and events[-1][1]["learned"] == ["new", "old", "report"] and left == []


def test_a_turn_that_changes_no_skill_learns_nothing(monkeypatch, fake_runner):
    hashes_in_turn(monkeypatch, {}, {})
    assert run_turn(monkeypatch, fake_runner, shell_then_done())[-1][1]["learned"] == []


@pytest.mark.parametrize("answers", [(OSError("runner"),), ({}, OSError("runner"))])
def test_a_failed_skill_check_still_ends_with_done(monkeypatch, fake_runner, answers):
    hashes_in_turn(monkeypatch, *answers)
    events = run_turn(monkeypatch, fake_runner, shell_then_done())
    assert events[-1][0] == "done" and "learned" not in events[-1][1]


def test_broken_skills_are_named_in_the_instructions(monkeypatch, fake_runner):
    from apps.agents.models.knowledge import Skill, Skills
    from apps.agents.services import knowledge_service

    broken = Skill(name="half-done", description="", path=".agent/skills/half-done/SKILL.md", status="skipped", problem="x")
    fine = Skill(name="report", description="d", path=".agent/skills/report/SKILL.md", status="ok", problem=None)

    async def listed(settings, agent_id):
        return Skills(skills=[broken, fine], truncated=False)

    monkeypatch.setattr(knowledge_service, "list_skills", listed)
    prompts = []
    real = agent_factory.instructions
    monkeypatch.setattr(agent_factory, "instructions", lambda *a: prompts.append(real(*a)) or prompts[-1])
    run_turn(monkeypatch, fake_runner, shell_then_done())
    assert "# Skills that need fixing" in prompts[0] and "'half-done': not loaded" in prompts[0] and "'report'" not in prompts[0]


def test_instructions_without_broken_skills_add_nothing():
    assert "need fixing" not in agent_factory.instructions("/w", get_settings(), "A", "")


def test_too_many_turns_is_429(client, user, fake_runner, monkeypatch):
    own(client, user, WS)
    monkeypatch.setenv("ECHO_MAX_RUNNING_TURNS", "1")
    get_settings.cache_clear()
    turn_service._running[user] = 1
    try:
        response = client.post(TURNS, json=turn("hi", ANY_KEY))
    finally:
        turn_service._running.clear()
    assert response.status_code == 429 and response.json()["error"]["code"] == "too_many_turns"


async def test_running_turns_are_counted_per_user_and_released(fake_runner):
    fake_runner.lines = [DONE]
    fake_runner.hold = "sleep 100"
    first = turn_service.stream_turn("k5", agent_maker(shell_then_done("sleep 100")), "go", 60, user_id="u1", max_running=1)
    assert (await anext(first)).startswith("event: text")
    # The same user's second chat is refused; another user is not.
    second = [e async for e in turn_service.stream_turn("k6", agent_maker(shell_then_done()), "go", 60, user_id="u1", max_running=1)]
    assert len(second) == 1 and "too_many_turns" in second[0]
    assert turn_service.can_start("u2", 1)
    await first.aclose()
    await wait_for(lambda: turn_service.can_start("u1", 1))
    assert "u1" not in turn_service._running


async def test_a_failed_turn_releases_its_slot(fake_runner):
    def explode(delegation):
        raise RuntimeError("boom")

    [e async for e in turn_service.stream_turn("k7", explode, "go", 60, user_id="u3", max_running=1)]
    await wait_for(lambda: turn_service.can_start("u3", 1))


class ParentAndChild(ScriptedModel):
    """Plays the parent's replies, or a subagent's when the call carries the harness's subagent
    role prompt, since the subagent shares the parent's model."""

    def __init__(self, parent: list, child: list):
        super().__init__(parent)
        self.child = ScriptedModel(child)
        self.child_prompts: list[str] = []

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        if "subagent handling a focused subtask" in (system_prompt or ""):
            self.child_prompts.append(system_prompt)
            async for event in self.child.stream(messages, tool_specs, system_prompt, **kwargs):
                yield event
            return
        async for event in super().stream(messages, tool_specs, system_prompt, **kwargs):
            yield event


def test_a_subagents_work_is_streamed(monkeypatch, fake_runner):
    plan = {"todos": [{"content": "Look", "activeForm": "Looking", "status": "in_progress"}]}
    model = ParentAndChild(
        [[("tool", "todo_write", plan), ("tool", "subagent", {"task": "Count the files"})], [("text", "Done.")]],
        [[("tool", "shell", {"command": "ls | wc -l"})], [("text", "3 files")]],
    )
    events = run_turn(monkeypatch, fake_runner, model)
    names = [e for e, _ in events]
    by_name = {e: d for e, d in events}
    sub_id = next(d["id"] for e, d in events if e == "tool" and d["name"] == "subagent")
    assert by_name["todos"] == {"items": [{"text": "Looking", "status": "in_progress"}]}
    assert ("tool_detail", {"id": sub_id, "detail": "Count the files"}) in events
    assert by_name["delegate"] == {"id": sub_id, "task": "Count the files"}
    assert by_name["delegate_tool"]["delegate"] == sub_id and by_name["delegate_tool"]["detail"] == "ls | wc -l"
    assert by_name["delegate_tool_result"]["ok"] is True
    assert by_name["delegate_done"] == {"id": sub_id, "ok": True}
    assert names.index("delegate") < names.index("delegate_done") < names.index("done") == len(names) - 1
    # The subagent ran in the agent's own workspace, with Echo's rules added to its role prompt.
    assert any(r["command"] == "ls | wc -l" and r["workspace_id"] == WS for r in fake_runner.requests)
    assert model.child_prompts and all("# Untrusted content" in p and f"/data/workspaces/{WS}" in p for p in model.child_prompts)
