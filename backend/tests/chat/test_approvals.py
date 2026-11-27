import asyncio
import concurrent.futures

from apps.chat.services import agent_factory, approvals, turn_service
from core.config import get_settings
from tests.chat.test_turns import DONE, WS, parse, shell_then_done, wait_for
from tests.helpers.accounts import own
from tests.helpers.scripted_model import ScriptedModel
from tests.helpers.turns import FakeWriter


def maker(model, chat):
    return lambda delegation, gate, mcp=None: agent_factory.build_agent(
        get_settings(), WS, chat, model, "anthropic/claude-sonnet-5-5", model, "Test agent", "", delegation=delegation, approvals=gate
    )


def start(chat, model, mode="ask", timeout=60, user="u1"):
    return turn_service.start_turn(FakeWriter(), WS, chat, maker(model, chat), "go", timeout, title="go", user_id=user, approval_mode=mode)


def events(turn, name):
    return [d for e, d in turn.events if e == name]


async def card(turn):
    await wait_for(lambda: len(events(turn, "approval_needed")) > len(events(turn, "approval_done")))
    return events(turn, "approval_needed")[-1]


def ran(fake_runner, command):
    return any(r.get("command") == command for r in fake_runner.requests)


def tool_results(model) -> list[str]:
    """The text of every tool result the model was given, in any call (the last one may be the
    memory extraction, which uses the same model)."""
    out = []
    for message in (m for call in model.all_messages for m in call):
        for block in message["content"]:
            if "toolResult" in block:
                out += [c.get("text", "") for c in block["toolResult"]["content"]]
    return out


async def test_ask_mode_waits_for_allow_then_runs(fake_runner):
    fake_runner.lines = [DONE]
    turn = start("1" * 32, shell_then_done("echo hi"))
    shown = await card(turn)
    assert shown["tool"] == "shell" and shown["input"] == {"command": "echo hi"} and shown["subagent"] is None
    assert not ran(fake_runner, "echo hi")
    assert approvals.answer(shown["id"], WS, "u1", "allow")
    await asyncio.wait_for(turn.ended.wait(), 5)
    assert ran(fake_runner, "echo hi") and turn.status == "done"
    assert events(turn, "approval_done") == [{"id": shown["id"], "decision": "allow"}]


async def test_deny_tells_the_model_and_the_turn_goes_on(fake_runner):
    model = shell_then_done("rm -rf x")
    turn = start("2" * 32, model)
    approvals.answer((await card(turn))["id"], WS, "u1", "deny")
    await asyncio.wait_for(turn.ended.wait(), 5)
    assert not ran(fake_runner, "rm -rf x") and turn.status == "done"
    assert any("The user denied this call" in t for t in tool_results(model))


async def test_allow_for_this_chat_holds_in_its_next_turn_but_not_another_chat(fake_runner):
    fake_runner.lines = [DONE]
    chat, other = "3" * 32, "4" * 32
    turn = start(chat, ScriptedModel([[("tool", "shell", {"command": "echo 1"})], [("tool", "shell", {"command": "echo 2"})], [("text", "ok")]]))
    approvals.answer((await card(turn))["id"], WS, "u1", "always")
    await asyncio.wait_for(turn.ended.wait(), 5)
    assert ran(fake_runner, "echo 2") and len(events(turn, "approval_needed")) == 1

    again = start(chat, shell_then_done("echo 3"))
    await asyncio.wait_for(again.ended.wait(), 5)
    assert ran(fake_runner, "echo 3") and events(again, "approval_needed") == []

    elsewhere = start(other, shell_then_done("echo 4"))
    await card(elsewhere)
    turn_service.stop(elsewhere)
    await asyncio.wait_for(elsewhere.ended.wait(), 5)
    assert not ran(fake_runner, "echo 4")


async def test_free_tools_and_yolo_never_ask(fake_runner):
    fake_runner.lines = [DONE]
    todo = ScriptedModel([[("tool", "todo_write", {"todos": [{"content": "a", "status": "pending"}]})], [("text", "ok")]])
    turn = start("5" * 32, todo)
    await asyncio.wait_for(turn.ended.wait(), 5)
    assert events(turn, "approval_needed") == []
    yolo = start("6" * 32, shell_then_done("echo y"), mode="yolo")
    await asyncio.wait_for(yolo.ended.wait(), 5)
    assert events(yolo, "approval_needed") == [] and ran(fake_runner, "echo y")


async def test_switching_to_yolo_lets_a_waiting_call_run(fake_runner):
    fake_runner.lines = [DONE]
    turn = start("7" * 32, shell_then_done("echo switch"))
    await card(turn)
    approvals.set_mode(WS, "yolo")
    await asyncio.wait_for(turn.ended.wait(), 5)
    assert ran(fake_runner, "echo switch") and events(turn, "approval_done")[0]["decision"] == "allow"


async def test_no_answer_denies(fake_runner, monkeypatch):
    monkeypatch.setattr(approvals, "WAIT_SECONDS", 0.2)
    model = shell_then_done("echo late")
    turn = start("8" * 32, model)
    await asyncio.wait_for(turn.ended.wait(), 5)
    assert not ran(fake_runner, "echo late") and events(turn, "approval_done")[0]["decision"] == "timeout"
    assert any("No one answered" in t for t in tool_results(model))


async def test_stopping_denies_but_leaving_the_stream_does_not(fake_runner):
    turn = start("9" * 32, shell_then_done("echo stop"))
    stream = turn_service.subscribe(turn)
    await anext(stream)
    await stream.aclose()
    shown = await card(turn)
    # A page that attaches later replays the waiting card and can still answer it.
    late = turn_service.subscribe(turn)
    replay = parse(await anext(late))
    await late.aclose()
    assert ("approval_needed", shown) in replay and not any(e == "approval_done" for e, _ in replay)
    turn_service.stop(turn)
    await asyncio.wait_for(turn.ended.wait(), 5)
    assert not ran(fake_runner, "echo stop") and events(turn, "approval_done")[0]["decision"] == "deny"
    assert not approvals.answer(shown["id"], WS, "u1", "allow")


async def test_the_wait_does_not_count_against_the_turn(fake_runner):
    fake_runner.lines = [DONE]
    turn = start("a1" * 16, shell_then_done("echo slow"), timeout=1)
    shown = await card(turn)
    await asyncio.sleep(1.5)
    approvals.answer(shown["id"], WS, "u1", "allow")
    await asyncio.wait_for(turn.ended.wait(), 5)
    assert turn.status == "done" and ran(fake_runner, "echo slow")


async def test_only_the_turns_own_user_and_agent_can_answer(fake_runner):
    turn = start("a2" * 16, shell_then_done("echo mine"))
    shown = await card(turn)
    assert not approvals.answer(shown["id"], WS, "someone else", "allow")
    assert not approvals.answer(shown["id"], "c" * 32, "u1", "allow")
    assert not approvals.answer("unknown", WS, "u1", "allow")
    turn_service.stop(turn)
    await asyncio.wait_for(turn.ended.wait(), 5)


def test_a_long_input_is_cut_on_the_card_only():
    gate = approvals.Approvals(WS, "u1", "ask", lambda sse: None)
    shown = gate._card("x", "write", {"content": "a" * 30_000}, agent=None)
    assert shown["input_cut"] is True and len(shown["input"]) == approvals.MAX_SHOWN_INPUT
    gate.close()


def test_a_subagents_card_names_its_task():
    class FakeDelegation:
        def task_for(self, agent):
            return "Survey the tests"

    gate = approvals.Approvals(WS, "u1", "ask", lambda sse: None, FakeDelegation())
    gate.parent = object()
    assert gate._card("x", "write", {}, agent=object())["subagent"] == "Survey the tests"
    gate.close()


def test_ask_mode_adds_the_approval_rule(fake_runner):
    gate = approvals.Approvals(WS, "u1", "ask", lambda sse: None)
    model = ScriptedModel([[("text", "hi")]])
    agent = maker(model, "a3" * 16)(turn_service.Delegation(lambda sse: None), gate)
    assert "# Approvals" in agent.system_prompt and gate.parent is agent
    gate.close()


def test_approval_route_answers_only_a_waiting_call(client, user):
    own(client, user, WS)
    response = client.post(f"/api/agents/{WS}/approvals/nothing", json={"decision": "allow"})
    assert response.status_code == 404 and response.json()["error"]["code"] == "approval_not_found"
    assert client.post(f"/api/agents/{WS}/approvals/nothing", json={"decision": "maybe"}).status_code == 422


def test_route_reaches_a_waiting_gate(client, user):
    own(client, user, WS)
    gate = approvals.Approvals(WS, user, "ask", lambda sse: None)
    future = concurrent.futures.Future()
    gate._waiting["id1"] = future
    approvals._pending["id1"] = gate
    try:
        assert client.post(f"/api/agents/{WS}/approvals/id1", json={"decision": "always"}).json()["data"] == {"decision": "always"}
        assert future.result(0) == "always"
    finally:
        approvals._pending.pop("id1", None)
        gate.close()


def test_mode_is_ask_by_default_and_can_be_switched(client, user, fake_runner):
    created = client.post("/api/agents", json={"name": "A"})
    assert created.status_code == 200 and created.json()["data"]["approval_mode"] == "ask"
    agent_id = created.json()["data"]["id"]
    changed = client.patch(f"/api/agents/{agent_id}", json={"approval_mode": "yolo"})
    assert changed.json()["data"]["approval_mode"] == "yolo"
    assert client.patch(f"/api/agents/{agent_id}", json={"approval_mode": "never"}).status_code == 422
