import json

import pytest

from apps.chat.services import process_tool as module
from core.config import get_settings

WS = "a" * 32


@pytest.fixture
def process(monkeypatch, fake_runner):
    monkeypatch.setattr(module, "SETTLE_SECONDS", 0)
    return module.process_tool(get_settings(), WS)


async def call(process, **params):
    async for event in process.stream({"toolUseId": "t", "name": "process", "input": params}, {}):
        last = event
    result = last["tool_result"]
    text = result["content"][0]["text"]
    return result["status"], (json.loads(text) if result["status"] == "success" else text)


async def test_start_reports_status_ports_and_first_log_lines(process, fake_runner):
    fake_runner.ports, fake_runner.process_log = [5173], "VITE ready on http://localhost:5173\n"
    status, data = await call(process, action="start", name="web", command="npm run dev", cwd="app")
    assert status == "success"
    assert data["process"]["status"] == "running" and data["ports"] == [5173] and "VITE ready" in data["log"]
    assert fake_runner.process_calls[0] == ("POST", WS, None, {"name": "web", "command": "npm run dev", "cwd": "app"})
    assert ("logs", WS, "web", module.START_LOG_LINES) in fake_runner.process_calls


async def test_list_logs_stop(process, fake_runner):
    await call(process, action="start", name="web", command="x")
    fake_runner.ports = [8000]
    assert (await call(process, action="list"))[1] == {"processes": [fake_runner.processes[WS]["web"]], "ports": [8000]}
    assert (await call(process, action="logs", name="web", tail=5000))[0] == "success"
    assert fake_runner.process_calls[-1] == ("logs", WS, "web", 1000)
    status, data = await call(process, action="stop", name="web")
    assert status == "success" and data["status"] == "exited"


@pytest.mark.parametrize("params, message", [
    ({"action": "stop"}, "needs a name"),
    ({"action": "start", "name": "web"}, "needs a command"),
    ({"action": "logs", "name": "nope"}, "There is no process named nope."),
])
async def test_mistakes_and_runner_errors_are_tool_errors(process, params, message):
    status, text = await call(process, **params)
    assert status == "error" and message in text


async def test_runner_refusal_reaches_the_agent(process, fake_runner):
    fake_runner.error = (429, {"success": False, "error": {"code": "too_many_processes", "message": "This workspace already runs 3 processes.", "details": None}})
    status, text = await call(process, action="start", name="web", command="x")
    assert status == "error" and "already runs 3 processes" in text


@pytest.mark.parametrize("name", ["../../x", "web/logs", "a%2Fb", "Web", ""])
async def test_a_bad_name_never_reaches_the_runner(process, fake_runner, name):
    for action in ("start", "stop", "logs"):
        status, _ = await call(process, action=action, name=name, command="x")
        assert status == "error"
    assert fake_runner.process_calls == []
