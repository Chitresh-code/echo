"""How much disk each workspace uses: its workspace folder plus its home. Measured after each
command and kept in memory, so a command never waits for a walk of a large workspace."""

import asyncio
import os
from pathlib import Path

from app import jail

# Bytes per workspace id, from the last measurement.
_used: dict[str, int] = {}


def _walk(roots: list[Path]) -> int:
    """Allocated bytes under the roots, so a sparse file counts what it really takes. Links are
    not followed and other filesystems are not entered, so a link the agent made cannot point the
    walk outside its folders. A file with several hard links is counted once."""
    total = 0
    seen: set[tuple[int, int]] = set()
    stack = [str(r) for r in roots if r.is_dir()]
    devices = {os.lstat(r).st_dev for r in stack}
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue  # removed while walking, or unreadable
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if st.st_dev not in devices:
                continue
            if st.st_nlink > 1:
                if (st.st_dev, st.st_ino) in seen:
                    continue
                seen.add((st.st_dev, st.st_ino))
            total += st.st_blocks * 512
            if entry.is_dir(follow_symlinks=False):
                stack.append(entry.path)
    return total


async def measure(settings: jail.Settings, workspace_id: str) -> int:
    roots = [jail.workspace_dir(settings, workspace_id), jail.home_dir(settings, workspace_id)]
    used = await asyncio.to_thread(_walk, roots)
    _used[workspace_id] = used
    return used


async def used(settings: jail.Settings, workspace_id: str) -> int:
    """The last measurement, or a fresh one after a runner restart."""
    if workspace_id in _used:
        return _used[workspace_id]
    return await measure(settings, workspace_id)


def limit(settings: jail.Settings) -> int:
    return settings.disk_mb * 1024 * 1024


def forget(workspace_id: str) -> None:
    _used.pop(workspace_id, None)


def over_limit_message(used_bytes: int, limit_bytes: int) -> str:
    mb = 1024 * 1024
    return (
        f"Echo: this workspace uses {used_bytes // mb} MB of its {limit_bytes // mb} MB limit, so files cannot be written. "
        "Delete files you do not need (for example node_modules or build output) to continue.\n"
    )
