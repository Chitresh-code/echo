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

from app import jail, main, net

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

    # Entered, so every request shares one event loop as under uvicorn; a process's output task
    # would otherwise die with the loop of the request that started it.
    with TestClient(main.create_app(live_settings)) as c:
        yield c


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


def _in_background(client, ws, command):
    """Run a command in another thread, for a server that must be up while other commands run."""
    thread = threading.Thread(target=run, args=(client, ws, command, 60), daemon=True)
    thread.start()
    return thread


def _wait_for(client, ws, url):
    out, _, _ = run(client, ws, f"for i in $(seq 50); do curl -s -o /dev/null -m 1 {url} && echo up && break; sleep 0.2; done")
    return out.strip() == "up"


def test_a_server_is_reachable_from_the_next_command(client):
    ws = new_ws(client)
    # Bound to loopback only, as dev servers usually are.
    thread = _in_background(client, ws, "cd /tmp && timeout 20 python3 -m http.server 8123 --bind 127.0.0.1")
    assert _wait_for(client, ws, "http://localhost:8123/")
    run(client, ws, "pkill -f 'http.server 8123' || true")
    thread.join(30)


def test_workspaces_cannot_reach_each_other(client, live_settings):
    a, b = new_ws(client), new_ws(client)
    thread = _in_background(client, a, "cd /tmp && timeout 20 python3 -m http.server 8124 --bind 0.0.0.0")
    assert _wait_for(client, a, "http://localhost:8124/")
    _, a_inside = net.addresses(net.index_of(live_settings, a))
    for url in ("http://localhost:8124/", f"http://{a_inside}:8124/"):
        out, _, _ = run(client, b, f"curl -s -o /dev/null -m 3 -w '%{{http_code}}' {url}; echo \" $?\"")
        code, curl_exit = out.split()
        assert code == "000" and curl_exit != "0", url
    run(client, a, "pkill -f 'http.server 8124' || true")
    thread.join(30)


def test_the_gateway_answers_only_dns(client, live_settings):
    ws = new_ws(client)
    gateway, _ = net.addresses(net.index_of(live_settings, ws))
    out, err, _ = run(client, ws, f"getent hosts pypi.org >/dev/null && echo dns; curl -s -o /dev/null -m 3 http://{gateway}/; echo \" $?\"")
    assert out.split() == ["dns", "28"], err  # 28: timed out, since anything but DNS is dropped


def test_a_jail_cannot_change_its_network(client):
    ws = new_ws(client)
    out, _, _ = run(client, ws, "ip link set eth0 down 2>/dev/null; echo $?; ip addr add 10.89.255.250/32 dev eth0 2>/dev/null; echo $?")
    assert "0" not in out.split()
    out, _, _ = run(client, ws, "curl -s -o /dev/null -w '%{http_code}' https://pypi.org/simple/pip/")
    assert out == "200"


def test_namespace_is_remade_after_it_is_gone(client, live_settings):
    ws = new_ws(client)
    # As after a container restart, which empties /run/netns.
    subprocess.run(["ip", "netns", "delete", net.name(ws)], check=True)
    out, err, _ = run(client, ws, "curl -s -o /dev/null -w '%{http_code}' https://pypi.org/simple/pip/")
    assert out == "200", err


def test_deleting_the_workspace_removes_its_namespace(client, live_settings):
    ws = new_ws(client)
    assert net.path(live_settings, ws).exists()
    assert client.delete(f"/workspaces/{ws}").status_code == 200
    assert not net.path(live_settings, ws).exists() and ws not in json.loads((DATA / "net" / "index.json").read_text())


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


def _processes(client, ws):
    return client.get(f"/workspaces/{ws}/processes").json()["data"]


def _wait_for_port(client, ws, port, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if port in (data := _processes(client, ws))["ports"]:
            return data
        time.sleep(0.2)
    raise AssertionError(data)


def test_a_process_outlives_its_request_and_is_reached_by_commands(client, live_settings):
    ws = new_ws(client)
    r = client.post(f"/workspaces/{ws}/processes", json={"name": "web", "command": "echo starting; exec python3 -m http.server 8130 --bind 127.0.0.1"})
    assert r.status_code == 200, r.text
    data = _wait_for_port(client, ws, 8130)
    assert data["processes"][0]["status"] == "running"
    out, _, _ = run(client, ws, "curl -s -o /dev/null -w '%{http_code}' http://localhost:8130/")
    assert out == "200"
    log = client.get(f"/workspaces/{ws}/processes/web/logs").json()["data"]["log"]
    assert "starting" in log and "GET / " in log
    # The log is the runner's, outside anything the jail can see.
    assert (live_settings.data_dir / "processes" / ws / "web.log").stat().st_uid == 0
    r = client.delete(f"/workspaces/{ws}/processes/web")
    assert r.json()["data"]["status"] == "exited"
    assert _processes(client, ws)["ports"] == []
    out, _, _ = run(client, ws, "curl -s -o /dev/null -m 2 -w '%{http_code}' http://localhost:8130/; echo \" $?\"")
    assert out.split()[0] == "000"


def test_process_limit_and_workspace_delete(client, live_settings):
    ws = new_ws(client)
    for n in range(live_settings.max_processes_per_workspace):
        assert client.post(f"/workspaces/{ws}/processes", json={"name": f"p{n}", "command": "sleep 600"}).status_code == 200
    r = client.post(f"/workspaces/{ws}/processes", json={"name": "more", "command": "sleep 600"})
    assert r.status_code == 429
    assert client.delete(f"/workspaces/{ws}").status_code == 200
    # nsjail and everything in the jail are gone, not just the table entry.
    cmdlines = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            cmdlines.append((proc / "cmdline").read_bytes())
        except OSError:
            pass
    assert not any(b"sleep\x00600" in c for c in cmdlines)
    assert not (live_settings.data_dir / "processes" / ws).exists()


def test_full_workspace_starts_a_process_that_cannot_write():
    from fastapi.testclient import TestClient

    from app import usage

    with TestClient(main.create_app(jail.Settings(data_dir=DATA, network=True, timeout_max=60, memory_mb=1024, disk_mb=1))) as client:
        _full_workspace_process(client, usage)


def _full_workspace_process(client, usage):
    ws = new_ws(client)
    run(client, ws, "head -c 2000000 /dev/zero > big")
    usage.forget(ws)
    r = client.post(f"/workspaces/{ws}/processes", json={"name": "w", "command": "echo more > other; echo exit=$?"})
    assert r.status_code == 200
    deadline = time.monotonic() + 10
    while _processes(client, ws)["processes"][0]["status"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.1)
    log = client.get(f"/workspaces/{ws}/processes/w/logs").json()["data"]["log"]
    assert "files cannot be written" in log and "exit=0" not in log


# A server that echoes POST bodies and the Host it saw, sets two cookies and sends a large body.
ECHO_SERVER = r'''
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/big"):
            self.send_response(200)
            self.send_header("Content-Length", str(20 * 1024 * 1024))
            self.end_headers()
            for _ in range(20):
                self.wfile.write(b"x" * 1024 * 1024)
            return
        body = f"{self.path} {self.headers['Host']}".encode()
        self.send_response(200)
        self.send_header("Set-Cookie", "a=1")
        self.send_header("Set-Cookie", "b=2")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(201)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

import socket
ThreadingHTTPServer.address_family = socket.AF_INET6 if ":" in sys.argv[1] else socket.AF_INET
ThreadingHTTPServer((sys.argv[1], int(sys.argv[2])), H).serve_forever()
'''


def _serve(client, ws, port, bind="127.0.0.1"):
    run(client, ws, f"cat > ~/server.py <<'PY'\n{ECHO_SERVER}\nPY")
    assert client.post(f"/workspaces/{ws}/processes", json={"name": "web", "command": f"exec python3 ~/server.py {bind} {port}"}).status_code == 200
    _wait_for_port(client, ws, port)


def test_preview_forwards_to_a_loopback_only_server(client):
    ws = new_ws(client)
    _serve(client, ws, 8140)
    base = f"/workspaces/{ws}/ports/8140/http"
    r = client.get(f"{base}/a/b%2Fc?x=1", headers={"Host": "localhost:8140"})
    assert r.status_code == 200 and r.text == "/a/b%2Fc?x=1 localhost:8140"
    assert r.headers.get_list("set-cookie") == ["a=1", "b=2"]
    r = client.post(f"{base}/form", content=b"hello" * 1000)
    assert r.status_code == 201 and r.content == b"hello" * 1000
    with client.stream("GET", f"{base}/big") as r:
        assert r.status_code == 200 and sum(len(chunk) for chunk in r.iter_raw()) == 20 * 1024 * 1024


def test_preview_reaches_a_server_on_ipv6_loopback(client):
    ws = new_ws(client)
    _serve(client, ws, 8141, bind="::1")
    assert client.get(f"/workspaces/{ws}/ports/8141/http/").status_code == 200


def test_preview_with_nothing_listening_and_no_thread_left_inside(client, live_settings):
    ws = new_ws(client)
    r = client.get(f"/workspaces/{ws}/ports/8142/http/")
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_unreachable"
    # Another workspace's server on the same port is not reached.
    other = new_ws(client)
    _serve(client, other, 8142)
    assert client.get(f"/workspaces/{ws}/ports/8142/http/").status_code == 502
    assert client.get(f"/workspaces/{other}/ports/8142/http/").status_code == 200
    # Every thread of the runner is still in the runner's own network namespace.
    own = os.readlink("/proc/self/ns/net")
    assert all(os.readlink(t / "ns" / "net") == own for t in Path("/proc/self/task").iterdir())
