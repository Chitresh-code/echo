import asyncio
import json

import pytest

from app import jail, net


@pytest.fixture
def ip_log(tmp_path):
    """A stand-in for ip that records its arguments and makes the namespace file on `netns add`."""
    log = tmp_path / "ip.log"
    fake = tmp_path / "ip"
    fake.write_text(f"""#!/bin/sh
printf "%s\\n" "$*" >> {log}
if [ "$1 $2" = "netns add" ]; then mkdir -p {tmp_path}/netns && touch {tmp_path}/netns/$3; fi
if [ "$1 $2" = "netns delete" ]; then rm {tmp_path}/netns/$3; fi
if [ -n "$FAIL_ON" ] && echo "$@" | grep -q "$FAIL_ON"; then exit 1; fi
""")
    fake.chmod(0o755)
    return log


def _settings(tmp_path, network=True):
    return jail.Settings(data_dir=tmp_path, network=network, timeout_max=30, memory_mb=64, ip=str(tmp_path / "ip"), netns_dir=tmp_path / "netns")


def test_addresses():
    assert net.addresses(0) == ("10.89.0.1", "10.89.0.2")
    assert net.addresses(70) == ("10.89.1.25", "10.89.1.26")
    assert net.addresses(net.MAX_INDEX - 1) == ("10.89.255.253", "10.89.255.254")


def test_index_is_stable_and_reuses_freed_slots(tmp_path, ip_log):
    s = _settings(tmp_path)
    a, b, c = "a" * 32, "b" * 32, "c" * 32
    assert [net.index_of(s, w) for w in (a, b, a)] == [0, 1, 0]
    asyncio.run(net.remove(s, a))
    assert net.index_of(s, c) == 0 and net.index_of(s, b) == 1


def test_ensure_makes_the_namespace_once(tmp_path, ip_log):
    s, ws = _settings(tmp_path), "d" * 32
    asyncio.run(net.ensure(s, ws))
    asyncio.run(net.ensure(s, ws))
    calls = ip_log.read_text().splitlines()
    assert calls[0] == f"netns add echo-{ws}" and sum(c.startswith("netns add") for c in calls) == 1
    assert f"link add ew0 type veth peer name eth0 netns echo-{ws}" in calls
    assert f"-n echo-{ws} route add default via 10.89.0.1" in calls
    assert net.resolv_conf(s, ws).read_text() == "nameserver 10.89.0.1\n"


def test_without_network_only_loopback(tmp_path, ip_log):
    s, ws = _settings(tmp_path, network=False), "e" * 32
    asyncio.run(net.ensure(s, ws))
    assert ip_log.read_text().splitlines() == [f"netns add echo-{ws}", f"-n echo-{ws} link set lo up"]
    assert not (tmp_path / "net" / "index.json").exists()


def test_half_made_namespace_is_removed(tmp_path, ip_log, monkeypatch):
    s, ws = _settings(tmp_path), "f" * 32
    monkeypatch.setenv("FAIL_ON", "route add")
    with pytest.raises(RuntimeError):
        asyncio.run(net.ensure(s, ws))
    assert not net.path(s, ws).exists() and not net.resolv_conf(s, ws).exists()


def test_remove_frees_the_index(tmp_path, ip_log):
    s, ws = _settings(tmp_path), "0" * 32
    asyncio.run(net.ensure(s, ws))
    asyncio.run(net.remove(s, ws))
    assert not net.path(s, ws).exists()
    assert json.loads((tmp_path / "net" / "index.json").read_text()) == {}
