"""Local MCP servers in a turn: the fake runner runs a real stdio MCP server from the SDK as a plain
subprocess, so the transport over the runner socket is tested end to end without a jail."""

import asyncio
import json
import sys
import textwrap

import pytest

from apps.chat.services import approvals, turn_service
from apps.mcp.services import connect, runner_stdio
from core.config import get_settings
from tests.chat.test_turns import WS, wait_for
from tests.helpers.scripted_model import ScriptedModel
from tests.helpers.turns import FakeWriter
from tests.mcp.test_connect import maker

ENV_VALUE = "local-key-3Jd8"

SERVER = textwrap.dedent("""
    import os, time
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("notes")

    @server.tool()
    def echo(text: str) -> str:
        \"\"\"Says the text back.\"\"\"
        return f"echo {text} key={os.environ.get('API_KEY') == 'local-key-3Jd8'}"

    @server.tool()
    def wait() -> str:
        time.sleep(30)
        return "late"

    server.run("stdio")
""")


@pytest.fixture
def script(tmp_path):
    path = tmp_path / "server.py"
    path.write_text(SERVER)
    return str(path)


def local_server(script, name="notes", tools_hash=None, args=None):
    # The real runner gets this env through the start request; the fake passes its own to the child.
    local = runner_stdio.Local(WS, get_settings().runner_socket, sys.executable, args if args is not None else [script], {"API_KEY": ENV_VALUE})
    return connect.TurnServer(f"id-{name}", name, "", "ok", tools_hash=tools_hash, local=local)


def start(chat, model, servers, writer=None):
    mcp = connect.TurnMcp(servers, "u1", WS)
    turn = turn_service.start_turn(writer or FakeWriter(), WS, chat, maker(model, chat), "go", 60, title="go", user_id="u1", mcp=mcp)
    return turn, mcp


async def test_a_turn_calls_a_local_tool_and_keeps_its_list(fake_runner, script):
    model = ScriptedModel([[("tool", "notes_echo", {"text": "hi"})], [("text", "done")]])
    turn, mcp = start("a" * 32, model, [local_server(script)])
    await wait_for(lambda: any(e == "approval_needed" for e, _ in turn.events), 20)
    card = next(d for e, d in turn.events if e == "approval_needed")
    assert card["server"] == "notes"
    approvals.answer(card["id"], WS, "u1", "allow")
    await asyncio.wait_for(turn.ended.wait(), 20)

    assert turn.status == "done"
    results = [c["text"] for m in model.all_messages[1] for b in m["content"] if "toolResult" in b for c in b["toolResult"]["content"]]
    assert results == ["echo hi key=False"]  # the fake does not pass env on; the real runner does, see below
    # The first turn's list becomes the reviewed one.
    change = mcp.changes["id-notes"]
    assert {t["name"] for t in change["tools"]} == {"echo", "wait"} and change["tools_hash"]
    # The env values go to the runner's start request and nowhere else.
    [started] = fake_runner.mcp_starts
    assert started["workspace_id"] == WS and started["env"] == {"API_KEY": ENV_VALUE} and started["args"] == [script]
    assert ENV_VALUE not in json.dumps(model.all_messages) + json.dumps(model.system_prompts) + json.dumps(turn.events)
    # The session is gone once the turn ends.
    await wait_for(lambda: not fake_runner.mcp, 5)


async def test_a_server_that_exits_reports_its_stderr_to_the_user_only(fake_runner, tmp_path):
    crash = tmp_path / "crash.py"
    crash.write_text("import sys\nprint('ModuleNotFoundError: no module named notes_db', file=sys.stderr)\nsys.exit(1)\n")
    model = ScriptedModel([[("text", "done")]])
    turn, _ = start("b" * 32, model, [local_server(str(crash))])
    await asyncio.wait_for(turn.ended.wait(), 30)
    [gone] = [d for e, d in turn.events if e == "mcp_unavailable"]
    assert gone["reason"] == connect.REASONS["exited"] and "no module named notes_db" in gone["detail"]
    assert "notes_db" not in model.system_prompts[0] and connect.REASONS["exited"] in model.system_prompts[0]


async def test_a_runner_refusal_names_the_limit(fake_runner, script):
    fake_runner.error = (409, {"success": False, "error": {"code": "too_many_mcp_servers", "message": "A workspace runs at most 5 MCP servers at once.", "details": None}})
    turn, _ = start("c" * 32, ScriptedModel([[("text", "done")]]), [local_server(script)])
    await asyncio.wait_for(turn.ended.wait(), 30)
    [gone] = [d for e, d in turn.events if e == "mcp_unavailable"]
    assert gone == {"server": "notes", "reason": connect.REASONS["runner"], "detail": "A workspace runs at most 5 MCP servers at once."}


async def test_a_stopped_turn_cancels_the_call_and_ends_the_session(fake_runner, script):
    turn, mcp = start("d" * 32, ScriptedModel([[("tool", "notes_wait", {})], [("text", "done")]]), [local_server(script)])
    await wait_for(lambda: any(e == "approval_needed" for e, _ in turn.events), 20)
    card = next(d for e, d in turn.events if e == "approval_needed")
    approvals.answer(card["id"], WS, "u1", "allow")
    await wait_for(lambda: any(m.get("method") == "tools/call" for m in fake_runner.mcp_sent), 10)
    turn_service.stop(turn)
    await asyncio.wait_for(turn.ended.wait(), 20)
    assert any(m.get("method") == "notifications/cancelled" for m in fake_runner.mcp_sent)
    await wait_for(lambda: not fake_runner.mcp, 5)
    assert mcp.clients == []
