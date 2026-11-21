import asyncio
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from strands.sandbox import ExecutionResult, StreamChunk
from strands.sandbox.errors import SandboxTimeoutError

from core.errors import AppError
from sandbox.runner_sandbox import RunnerSandbox, runner_client

WS = "a" * 32


@pytest.fixture
def sandbox(fake_runner):
    return RunnerSandbox(WS, fake_runner.socket_path, default_timeout=120)


async def collect(sandbox, command="echo hi", **kwargs):
    return [item async for item in sandbox.execute_streaming(command, **kwargs)]


async def test_lines_become_chunks_then_result(sandbox, fake_runner):
    fake_runner.lines = [
        {"stream": "stdout", "data": "one\n"},
        {"stream": "stderr", "data": "warn\n"},
        {"stream": "stdout", "data": "two\n"},
        {"exit_code": 3, "timed_out": False},
    ]
    items = await collect(sandbox, timeout=4.2, cwd="/data/workspaces/x", env={"A": "1"})
    assert items == [
        StreamChunk("one\n", "stdout"),
        StreamChunk("warn\n", "stderr"),
        StreamChunk("two\n", "stdout"),
        ExecutionResult(3, "one\ntwo\n", "warn\n"),
    ]
    assert fake_runner.requests == [{"workspace_id": WS, "command": "echo hi", "timeout": 5, "cwd": "/data/workspaces/x", "env": {"A": "1"}}]


async def test_default_timeout_is_sent(sandbox, fake_runner):
    fake_runner.lines = [{"exit_code": 0, "timed_out": False}]
    await collect(sandbox)
    assert fake_runner.requests[0]["timeout"] == 120


async def test_timed_out_raises_with_output_so_far(sandbox, fake_runner):
    fake_runner.lines = [{"stream": "stdout", "data": "partial"}, {"exit_code": 137, "timed_out": True}]
    with pytest.raises(SandboxTimeoutError) as info:
        await collect(sandbox, timeout=2)
    assert info.value.stdout == "partial"


async def test_runner_error_becomes_app_error(sandbox, fake_runner):
    fake_runner.error = (404, {"success": False, "error": {"code": "workspace_not_found", "message": "There is no workspace with this id.", "details": None}})
    with pytest.raises(AppError) as info:
        await collect(sandbox)
    assert (info.value.status_code, info.value.code) == (404, "workspace_not_found")


async def test_non_envelope_error_is_generic(sandbox, fake_runner):
    fake_runner.error = (500, {"detail": "boom"})
    with pytest.raises(AppError) as info:
        await collect(sandbox)
    assert info.value.code == "runner_error"


async def test_stream_without_exit_line_is_an_error(sandbox, fake_runner):
    fake_runner.lines = [{"stream": "stdout", "data": "x"}]
    with pytest.raises(OSError):
        await collect(sandbox)


async def test_bad_env_key_is_rejected_before_calling_the_runner(sandbox, fake_runner):
    with pytest.raises(ValueError):
        await collect(sandbox, env={"BAD KEY": "1"})
    assert fake_runner.requests == []


async def test_closing_the_stream_early_closes_the_request(sandbox, fake_runner):
    fake_runner.lines = [{"stream": "stdout", "data": "started\n"}]
    fake_runner.hold = True
    stream = sandbox.execute_streaming("sleep 100")
    assert await anext(stream) == StreamChunk("started\n", "stdout")
    await stream.aclose()
    assert await asyncio.to_thread(fake_runner.closed.wait, 5)


async def test_inherited_execute_returns_the_result(sandbox, fake_runner):
    fake_runner.lines = [{"stream": "stdout", "data": "hi\n"}, {"exit_code": 0, "timed_out": False}]
    assert (await sandbox.execute("echo hi")).stdout == "hi\n"


def test_startup_fails_without_the_runner(monkeypatch, tmp_path):
    from core.config import get_settings
    from main import create_app

    monkeypatch.setenv("ECHO_RUNNER_SOCKET", str(tmp_path / "missing.sock"))
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="did not answer"):
        with TestClient(create_app()):
            pass


@pytest.mark.stack
async def test_binary_file_round_trips_through_the_real_runner():
    socket_path = Path(os.environ.get("ECHO_RUNNER_SOCKET", "/run/echo/runner.sock"))
    ws = uuid.uuid4().hex
    async with runner_client(socket_path) as client:
        (await client.post(f"/workspaces/{ws}")).raise_for_status()
    sandbox = RunnerSandbox(ws, socket_path, default_timeout=60)
    content = bytes(range(256)) * 64
    await sandbox.write_file("nested/dir/blob.bin", content)
    assert await sandbox.read_file("nested/dir/blob.bin") == content
    assert (await sandbox.execute("git rev-parse --is-inside-work-tree")).stdout == "true\n"


def test_startup_fails_for_an_unusable_model(monkeypatch, fake_runner):
    from fastapi.testclient import TestClient

    from core.config import get_settings
    from main import create_app

    monkeypatch.setenv("ECHO_MODELS", "nosuchprovider/some-model")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="nosuchprovider/some-model cannot be used"):
        with TestClient(create_app()):
            pass
