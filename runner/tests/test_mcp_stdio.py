import asyncio
import dataclasses
import json
import os
import sys
import textwrap

import pytest
from fastapi.testclient import TestClient

from app import jail, main, mcp_stdio, processes

# Answers each message with its own params, says "said" on stderr, and treats a few methods as commands.
SERVER = textwrap.dedent("""
    import json, sys
    print("starting", file=sys.stderr, flush=True)
    for line in sys.stdin:
        m = json.loads(line)
        if m["method"] == "argv":
            out = {"argv": sys.argv[1:]}
        elif m["method"] == "junk":
            print("not json", flush=True); continue
        elif m["method"] == "big":
            print(json.dumps({"x": "a" * (5 * 1024 * 1024)}), flush=True); continue
        elif m["method"] == "exit":
            print("bye now", file=sys.stderr, flush=True); sys.exit(3)
        else:
            out = m.get("params")
        print(json.dumps({"id": m["id"], "result": out}), flush=True)
""")


@pytest.fixture
def server(fake_settings):
    path = fake_settings.data_dir / "server.py"
    path.write_text(SERVER)
    return str(path)


def _argv_for(settings, ws):
    async def argv_for(program, timeout):
        return jail.build_argv(settings, ws, None, timeout, None, None, program=program)
    return argv_for


@pytest.fixture
def sessions(fake_settings, ws_id):
    jail.workspace_dir(fake_settings, ws_id).mkdir(parents=True)
    return mcp_stdio.Sessions(fake_settings, processes.Registry(fake_settings))


async def _start(sessions, settings, ws, server, *args):
    return await sessions.start(ws, sys.executable, [server, *args], {}, _argv_for(settings, ws))


async def _read(stream, n):
    return [await asyncio.wait_for(anext(stream), 10) for _ in range(n)]


@pytest.mark.asyncio
async def test_round_trip_and_exit_with_stderr(sessions, fake_settings, ws_id, server):
    s = await _start(sessions, fake_settings, ws_id, server, "$(echo hi)", "a b")
    sessions.claim(s)
    stream = sessions.messages(s)
    await sessions.send(s, {"id": 1, "method": "echo", "params": {"q": 1}})
    await sessions.send(s, {"id": 2, "method": "argv"})
    got = await _read(stream, 2)
    assert got[0] == {"message": {"id": 1, "result": {"q": 1}}}
    # The arguments reach the program as they were given: no shell expanded them.
    assert got[1]["message"]["result"] == {"argv": ["$(echo hi)", "a b"]}
    await sessions.send(s, {"id": 3, "method": "exit"})
    [end] = await _read(stream, 1)
    assert end["exit"] == 3 and "bye now" in end["stderr"] and "starting" in end["stderr"]
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert sessions.count() == 0 and not sessions.table[ws_id]
    with pytest.raises(jail.JailError) as e:
        await sessions.send(s, {"id": 4, "method": "echo"})
    assert e.value.code == "mcp_session_ended"


@pytest.mark.asyncio
@pytest.mark.parametrize("method, note", [("junk", "not a JSON message"), ("big", "over 4 MB")])
async def test_bad_output_kills_the_server(sessions, fake_settings, ws_id, server, method, note):
    s = await _start(sessions, fake_settings, ws_id, server)
    sessions.claim(s)
    stream = sessions.messages(s)
    await sessions.send(s, {"id": 1, "method": method})
    [end] = await _read(stream, 1)
    assert "exit" in end and note in end["stderr"] and s.ended


@pytest.mark.asyncio
async def test_closing_the_stream_kills_the_jail(sessions, fake_settings, ws_id, server):
    s = await _start(sessions, fake_settings, ws_id, server)
    sessions.claim(s)
    stream = sessions.messages(s)
    await sessions.send(s, {"id": 1, "method": "echo"})
    await _read(stream, 1)
    await stream.aclose()
    assert s.ended and s.id not in sessions.table[ws_id]


@pytest.mark.asyncio
async def test_one_reader(sessions, fake_settings, ws_id, server):
    s = await _start(sessions, fake_settings, ws_id, server)
    sessions.claim(s)
    with pytest.raises(jail.JailError) as e:
        sessions.claim(s)
    assert e.value.code == "mcp_session_busy"
    await sessions.stop_workspace(ws_id)
    assert s.ended and ws_id not in sessions.table


@pytest.mark.asyncio
async def test_limits_are_shared_with_processes(sessions, fake_settings, ws_id, server):
    for _ in range(mcp_stdio.MAX_PER_WORKSPACE):
        await _start(sessions, fake_settings, ws_id, server)
    with pytest.raises(jail.JailError) as e:
        await _start(sessions, fake_settings, ws_id, server)
    assert e.value.code == "too_many_mcp_servers"
    # Sandbox-wide: five servers plus fifteen processes fill the default twenty.
    other = "b" * 32
    jail.workspace_dir(fake_settings, other).mkdir(parents=True)
    sessions.settings = sessions.registry.settings = dataclasses.replace(fake_settings, max_processes=6)
    await _start(sessions, fake_settings, other, server)
    with pytest.raises(jail.JailError) as e:
        await _start(sessions, fake_settings, other, server)
    assert e.value.code == "too_many_processes"
    with pytest.raises(jail.JailError) as e:
        await sessions.registry.start(other, "web", "sleep 1", None, None)
    assert e.value.code == "too_many_processes"
    await sessions.stop_all()


@pytest.mark.parametrize("command, args, env, code", [
    ("", [], {}, "invalid_mcp_command"),
    ("x" * 501, [], {}, "invalid_mcp_command"),
    ("npx", ["a\0b"], {}, "invalid_mcp_command"),
    ("npx", ["a"] * 51, {}, "invalid_mcp_command"),
    ("npx", [], {"HOME": "/"}, "invalid_env"),
    ("npx", [], {"PATH": "/x"}, "invalid_env"),
    ("npx", [], {"NSJAIL_X": "1"}, "invalid_env"),
    ("npx", [], {"A-B": "1"}, "invalid_env"),
    ("npx", [], {f"K{i}": "1" for i in range(21)}, "invalid_env"),
])
def test_program_checks(command, args, env, code):
    with pytest.raises(jail.JailError) as e:
        mcp_stdio.check_program(command, args, env)
    assert e.value.code == code


def test_argv_execs_without_a_shell(settings, ws_id):
    argv = jail.build_argv(settings, ws_id, None, 60, None, {"API_KEY": "k"}, program=["npx", "-y", "$(x)"])
    assert argv[-6:] == ["--", "/usr/bin/env", "--", "npx", "-y", "$(x)"]
    assert "/bin/sh" not in argv and "API_KEY=k" in " ".join(argv)


def test_routes(fake_settings, ws_id, server, monkeypatch):
    monkeypatch.setattr(os, "chown", lambda *a: None)
    with TestClient(main.create_app(fake_settings)) as client:
        client.post(f"/workspaces/{ws_id}")
        r = client.post(f"/workspaces/{ws_id}/mcp", json={"command": sys.executable, "args": [server]})
        sid = r.json()["data"]["id"]
        base = f"/workspaces/{ws_id}/mcp/{sid}"
        assert client.post(f"{base}/messages", content=b"[1]").json()["error"]["code"] == "validation_error"
        assert client.post(f"{base}/messages", json={"id": 1, "method": "exit"}).json()["data"] == {"sent": True}
        lines = [json.loads(line) for line in client.get(f"{base}/messages").iter_lines() if line]
        assert lines[-1]["exit"] == 3 and "bye now" in lines[-1]["stderr"]
        assert client.get(f"{base}/messages").json()["error"]["code"] == "mcp_session_not_found"
        assert client.get(f"/workspaces/{ws_id}/mcp/{'0' * 32}/messages").status_code == 404
        assert client.post(f"/workspaces/{ws_id}/mcp", json={"command": "x", "env": {"HOME": "/"}}).json()["error"]["code"] == "invalid_env"
        # A workspace delete stops its servers.
        sid = client.post(f"/workspaces/{ws_id}/mcp", json={"command": sys.executable, "args": [server]}).json()["data"]["id"]
        assert client.delete(f"/workspaces/{ws_id}").status_code == 200
        assert client.post(f"/workspaces/{ws_id}/mcp/{sid}/messages", json={"id": 1}).status_code == 404
