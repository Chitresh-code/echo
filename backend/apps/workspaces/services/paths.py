"""Checks on what a caller sends before anything reaches the runner. The jail already limits what a
bad path can reach; these give clean 400 errors instead of confusing shell failures."""

import posixpath
import re

from core.errors import AppError

WORKSPACE_ID = re.compile(r"[0-9a-f]{32}")


def check_workspace_id(workspace_id: str) -> str:
    if not WORKSPACE_ID.fullmatch(workspace_id):
        raise AppError(400, "invalid_workspace_id", "A workspace id is 32 lowercase hex characters.")
    return workspace_id


def safe_relpath(path: str) -> str:
    """A normalized path relative to the workspace root, or a 400."""
    if not path or "\0" in path or path.startswith("/") or ".." in path.split("/"):
        raise AppError(400, "invalid_path", "The path must be relative to the workspace and stay inside it.")
    normal = posixpath.normpath(path)
    if normal == ".":
        raise AppError(400, "invalid_path", "The path must name a file in the workspace.")
    return normal
