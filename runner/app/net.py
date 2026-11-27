"""A network namespace per workspace, so its jails share one loopback (a server started by one
command is reachable from the next) and no other workspace can reach it.

With networking on, the namespace gets a veth pair to the sandbox container: `ew<n>` outside at
10.89.0.0/16 + 4n + 1, `eth0` inside at + 2, a default route through it, and DNS at the outside
address, where the entrypoint's dnsmasq answers. The entrypoint's firewall applies to everything
forwarded from `ew+`. With networking off the namespace has loopback only.

Namespaces live in /run/netns, which a container restart empties, so they are made on first use
and remade after a restart. The index n is kept on disk so a workspace keeps its addresses."""

import asyncio
import ipaddress
import json
import os
from pathlib import Path

from app import jail

BASE = ipaddress.IPv4Address("10.89.0.0")
# A /30 per workspace in 10.89.0.0/16.
MAX_INDEX = 2**16 // 4

# Namespaces are made rarely and the index file is read-modify-write, so one lock is enough.
_lock = asyncio.Lock()


def name(workspace_id: str) -> str:
    return f"echo-{jail.check_id(workspace_id)}"


def path(settings: jail.Settings, workspace_id: str) -> Path:
    return settings.netns_dir / name(workspace_id)


def resolv_conf(settings: jail.Settings, workspace_id: str) -> Path:
    return settings.data_dir / "net" / "resolv" / f"{jail.check_id(workspace_id)}.conf"


def addresses(index: int) -> tuple[str, str]:
    """The outside (gateway and DNS) and inside addresses of workspace index `index`."""
    return str(BASE + 4 * index + 1), str(BASE + 4 * index + 2)


def _index_file(settings: jail.Settings) -> Path:
    return settings.data_dir / "net" / "index.json"


def _read_index(settings: jail.Settings) -> dict[str, int]:
    try:
        return json.loads(_index_file(settings).read_text())
    except FileNotFoundError:
        return {}


def _write_index(settings: jail.Settings, index: dict[str, int]) -> None:
    file = _index_file(settings)
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps(index))
    os.replace(tmp, file)


def index_of(settings: jail.Settings, workspace_id: str) -> int:
    """The workspace's index, given the lowest free one the first time."""
    index = _read_index(settings)
    if workspace_id in index:
        return index[workspace_id]
    used = set(index.values())
    free = next((n for n in range(MAX_INDEX) if n not in used), None)
    if free is None:
        raise RuntimeError("No network addresses left for another workspace.")
    index[workspace_id] = free
    _write_index(settings, index)
    return free


async def _ip(settings: jail.Settings, *args: str, check: bool = True) -> None:
    proc = await asyncio.create_subprocess_exec(settings.ip, *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if check and proc.returncode != 0:
        raise RuntimeError(f"ip {' '.join(args)} failed: {err.decode(errors='replace').strip()}")


async def ensure(settings: jail.Settings, workspace_id: str) -> None:
    """Make the workspace's namespace unless it exists. Called before every jail."""
    if path(settings, workspace_id).exists():
        return
    async with _lock:
        if path(settings, workspace_id).exists():
            return
        ns = name(workspace_id)
        try:
            await _ip(settings, "netns", "add", ns)
            await _ip(settings, "-n", ns, "link", "set", "lo", "up")
            if settings.network:
                n = index_of(settings, workspace_id)
                outside, inside = addresses(n)
                veth = f"ew{n}"
                # The kernel tears down a deleted namespace's devices later, so the old veth of a
                # namespace that just went away may still be here.
                await _ip(settings, "link", "delete", veth, check=False)
                await _ip(settings, "link", "add", veth, "type", "veth", "peer", "name", "eth0", "netns", ns)
                await _ip(settings, "addr", "add", f"{outside}/30", "dev", veth)
                await _ip(settings, "link", "set", veth, "up")
                await _ip(settings, "-n", ns, "addr", "add", f"{inside}/30", "dev", "eth0")
                await _ip(settings, "-n", ns, "link", "set", "eth0", "up")
                await _ip(settings, "-n", ns, "route", "add", "default", "via", outside)
                conf = resolv_conf(settings, workspace_id)
                conf.parent.mkdir(parents=True, exist_ok=True)
                conf.write_text(f"nameserver {outside}\n")
                conf.chmod(0o644)
        except BaseException:
            # Half made: remove it so the next jail starts over instead of using a namespace with no route.
            await _remove(settings, workspace_id)
            raise


async def _remove(settings: jail.Settings, workspace_id: str) -> None:
    n = _read_index(settings).get(workspace_id)
    if settings.network and n is not None:
        # Deleting one end removes both at once; left to the namespace's deletion it happens later.
        await _ip(settings, "link", "delete", f"ew{n}", check=False)
    if path(settings, workspace_id).exists():
        await _ip(settings, "netns", "delete", name(workspace_id))
    resolv_conf(settings, workspace_id).unlink(missing_ok=True)


async def remove(settings: jail.Settings, workspace_id: str) -> None:
    """Delete the namespace and free the workspace's addresses, when the workspace is deleted."""
    async with _lock:
        await _remove(settings, workspace_id)
        index = _read_index(settings)
        if index.pop(workspace_id, None) is not None:
            _write_index(settings, index)
