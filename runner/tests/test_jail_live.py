"""Real jails behind the real firewall. These run only in the sandbox image, as root, after the
entrypoint has installed the firewall: `docker compose -f compose.test.yml run --rm sandbox-test`."""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
import uvicorn

from app import jail, main

pytestmark = pytest.mark.jail

# Not under /tmp: every jail mounts a private tmpfs there, which would hide the workspace.
DATA = Path("/data/jail-tests")


@pytest.fixture(scope="module")
def live_settings():
    shutil.rmtree(DATA, ignore_errors=True)
    # The shipped memory limit, so installs and builds are tested under what users get.
    s = jail.Settings(data_dir=DATA, network=True, timeout_max=120, memory_mb=jail.load_settings({}).memory_mb)
    yield s
    shutil.rmtree(DATA, ignore_errors=True)


@pytest.fixture(scope="module")
def client(live_settings):
    from fastapi.testclient import TestClient

    return TestClient(main.create_app(live_settings))


def new_ws(client) -> str:
    ws = uuid.uuid4().hex
    assert client.post(f"/workspaces/{ws}").status_code == 200
    return ws


def run(client, ws, command, timeout=60, **extra):
    r = client.post(f"/workspaces/{ws}/exec", json={"command": command, "timeout": timeout, **extra})
    assert r.status_code == 200, r.text
    lines = [json.loads(line) for line in r.text.splitlines()]
    out = "".join(line["data"] for line in lines if line.get("stream") == "stdout")
    err = "".join(line["data"] for line in lines if line.get("stream") == "stderr")
    return out, err, lines[-1]


def test_workspace_is_a_git_repo_owned_by_the_jail_user(client, live_settings):
    ws = new_ws(client)
    path = live_settings.data_dir / "workspaces" / ws
    assert (path / ".git").is_dir() and (path / ".agent" / "skills").is_dir()
    assert path.stat().st_uid == 1000 and (live_settings.data_dir / "homes" / ws).stat().st_uid == 1000
    out, _, end = run(client, ws, "id -u; echo hi > a && git add a && git commit -qm first && git log --format=%an")
    assert out.split() == ["1000", "Echo"] and end["exit_code"] == 0


def test_long_command_runs_and_cannot_change_its_own_file(client, live_settings):
    ws = new_ws(client)
    out, _, end = run(client, ws, f"echo {'a' * 300_000} | wc -c; echo x >> \"$0\" && echo wrote; ls {live_settings.data_dir}/commands")
    lines = out.split()
    assert lines[0] == "300001" and "wrote" not in lines and len(lines) == 2


def test_cannot_see_other_workspaces_or_homes(client, live_settings):
    a, b = new_ws(client), new_ws(client)
    run(client, b, "echo secret > s; echo secret > ~/s")
    out, _, _ = run(client, a, f"ls {live_settings.data_dir}/workspaces; ls {live_settings.data_dir}/homes; cat {live_settings.data_dir}/workspaces/{b}/s; ls /home")
    assert "secret" not in out and b not in out
    assert sorted(out.split()) == sorted([a, "echo"])
    # The runner's code and its socket directory are not in the jail at all.
    out, _, _ = run(client, a, "test -e /opt || test -e /run/echo || echo absent")
    assert out.strip() == "absent"


def test_no_parent_environment(client):
    os.environ["ECHO_TEST_SECRET"] = "leak"
    ws = new_ws(client)
    out, _, _ = run(client, ws, "env")
    assert "leak" not in out and "RUNNER_" not in out
    assert "HOME=/home/echo" in out


def test_toolchains_run(client):
    ws = new_ws(client)
    out, err, end = run(client, ws, "node -e 'console.log(6*7)' && python3 -c 'print(6*7)' && uv --version >/dev/null && echo ok")
    assert out.split() == ["42", "42", "ok"], err


def test_reaches_the_internet_through_dns(client):
    ws = new_ws(client)
    out, err, _ = run(client, ws, "curl -sS -o /dev/null -w '%{http_code}' https://pypi.org/simple/pip/")
    assert out == "200", err


def _own_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 80))  # no packet is sent; this only picks the outbound address
        return s.getsockname()[0]


@pytest.fixture(scope="module")
def local_server():
    # A server the jail must not reach: on all addresses, as root, like the runner or a
    # neighbouring container would be.
    proc = subprocess.Popen(["python3", "-m", "http.server", "18080", "--bind", "0.0.0.0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", 18080), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield
    proc.terminate()


@pytest.mark.parametrize("target", ["127.0.0.1:18080", "OWN_IP:18080", "169.254.169.254", "host.docker.internal:18080", "[::1]:18080"])
def test_private_and_metadata_addresses_refused(client, local_server, target):
    target = target.replace("OWN_IP", _own_ip())
    assert subprocess.run(["curl", "-s", "-o", "/dev/null", "-m", "3", f"http://127.0.0.1:18080/"]).returncode == 0  # root still can
    ws = new_ws(client)
    out, _, _ = run(client, ws, f"curl -s -o /dev/null -m 3 -w '%{{http_code}}' http://{target}/; echo \" $?\"")
    code, curl_exit = out.split()
    assert code == "000" and curl_exit != "0"


def test_webassembly_runs(client):
    # Node reserves gigabytes of address space per WebAssembly memory, which an address-space cap refuses.
    out, err, end = run(client, new_ws(client), "node -e 'new WebAssembly.Memory({initial: 1, maximum: 65536}); console.log(\"ok\")'")
    assert out == "ok\n" and end["exit_code"] == 0, err


def test_memory_limit_kills_the_jail(live_settings):
    from fastapi.testclient import TestClient

    small = jail.Settings(data_dir=DATA, network=True, timeout_max=60, memory_mb=128)
    client = TestClient(main.create_app(small))
    _, _, end = run(client, new_ws(client), "node -e 'const a = []; for (;;) a.push(Buffer.alloc(16 << 20, 1))'", timeout=30)
    # Killed by the cgroup's OOM killer (SIGKILL), well before the time limit.
    assert end["exit_code"] == jail.KILLED_EXIT and end["timed_out"] is False
    assert not [d for d in Path(jail.CGROUP_PARENT).iterdir() if d.name.startswith("NSJAIL")]


def test_time_limit(client):
    ws = new_ws(client)
    started = time.monotonic()
    out, _, end = run(client, ws, "echo start; sleep 30", timeout=2)
    assert out == "start\n" and end["timed_out"] is True
    assert time.monotonic() - started < 10


def test_user_installs_persist_between_commands(client):
    ws = new_ws(client)
    _, err, end = run(client, ws, "pip install --user --quiet --disable-pip-version-check six==1.17.0", timeout=120)
    assert end["exit_code"] == 0, err
    out, err, _ = run(client, ws, "python3 -c 'import six; print(six.__version__)'")
    assert out.strip() == "1.17.0", err


def test_npm_global_install_lands_in_home(client):
    ws = new_ws(client)
    _, err, end = run(client, ws, "npm install -g --silent cowsay@1.6.0", timeout=120)
    assert end["exit_code"] == 0, err
    out, _, _ = run(client, ws, "command -v cowsay")
    assert out.strip() == "/home/echo/.local/bin/cowsay"


def test_symlink_to_host_file_unreadable(client):
    ws = new_ws(client)
    out, _, _ = run(client, ws, "ln -s /etc/shadow s; cat s; echo \" $?\"")
    assert out.strip().endswith("1") and "root:" not in out


def test_system_directories_read_only(client):
    ws = new_ws(client)
    out, _, _ = run(client, ws, "touch /usr/x /etc/x /bin/x 2>/dev/null; echo $?")
    assert out.strip() != "0"


def test_client_disconnect_kills_the_jail(live_settings):
    path = Path(f"/run/echo-test-{uuid.uuid4().hex[:8]}.sock")
    sock = main.bind_socket(path, 0)
    server = uvicorn.Server(uvicorn.Config(main.create_app(live_settings), fd=sock.fileno(), log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    transport = httpx.HTTPTransport(uds=str(path))
    with httpx.Client(transport=transport, base_url="http://runner", timeout=30) as http:
        for _ in range(50):
            try:
                http.get("/health")
                break
            except httpx.TransportError:
                time.sleep(0.1)
        ws = uuid.uuid4().hex
        http.post(f"/workspaces/{ws}")
        with http.stream("POST", f"/workspaces/{ws}/exec", json={"command": "echo up; sleep 300", "timeout": 600}) as r:
            # Kept in a variable: a discarded line iterator closes the response, which is itself a disconnect.
            lines = r.iter_lines()
            assert json.loads(next(lines)) == {"stream": "stdout", "data": "up\n"}
            assert _running()
    deadline = time.monotonic() + 10
    while _running() and time.monotonic() < deadline:
        time.sleep(0.2)
    server.should_exit = True
    assert not _running()


def _running() -> bool:
    """Whether any jailed process is alive. Jailed processes run as uid 1000, which nothing else
    in the test container uses, and stay visible here from the parent pid namespace."""
    for status in Path("/proc").glob("[0-9]*/status"):
        try:
            text = status.read_text()
        except OSError:
            continue
        uid_line = next((line for line in text.splitlines() if line.startswith("Uid:")), "")
        if uid_line.split()[1:2] == ["1000"] and "State:\tZ" not in text:
            return True
    return False


def test_entrypoint_fails_closed_when_iptables_fails(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    for tool in ("iptables", "ip6tables"):
        (fake / tool).write_text("#!/bin/sh\nexit 1\n")
        (fake / tool).chmod(0o755)
    r = subprocess.run(
        ["/opt/runner/entrypoint.sh", "echo", "started"],
        env={"PATH": f"{fake}:/usr/bin:/bin", "RUNNER_JAIL_NETWORK": "1"}, capture_output=True, text=True,
    )
    assert r.returncode != 0 and "started" not in r.stdout


def test_full_workspace_can_delete_but_not_write(live_settings):
    from fastapi.testclient import TestClient

    from app import usage

    client = TestClient(main.create_app(jail.Settings(data_dir=DATA, network=True, timeout_max=60, memory_mb=1024, disk_mb=1)))
    ws = new_ws(client)
    run(client, ws, "head -c 2000000 /dev/zero > big && git add big && git commit -qm big")
    usage.forget(ws)  # the after-command measurement runs in the background; measure now
    out, err, end = run(client, ws, "git status --short; echo more > other; echo exit=$?")
    assert "files cannot be written" in err and "exit=0" not in out
    out, _, end = run(client, ws, "git rm -q --cached big >/dev/null 2>&1; rm big; ls")
    assert "big" not in out.split()
    usage.forget(ws)
    out, err, end = run(client, ws, "echo ok > small && cat small")
    assert out.strip() == "ok" and "files cannot be written" not in err
