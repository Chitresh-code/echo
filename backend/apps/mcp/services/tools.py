"""Checks on what an MCP server offers. A server is outside Echo's control: its tool names become
part of the model's tool list and its descriptions part of the prompt, so both are bounded, and the
whole list is fingerprinted so a server that changes its tools after review is noticed."""

import hashlib
import json
import re

# What a model provider accepts as a tool name, after the server's name and "_" are put in front.
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_DESCRIPTION = 2000
MAX_TOOLS = 100


def clean(server_name: str, tools: list[dict]) -> list[dict]:
    """The tools Echo offers from a server, each `{name, description, input_schema, annotations}`:
    a name that would be invalid or repeated once prefixed is dropped, a long description is cut,
    and only the first MAX_TOOLS are kept."""
    kept: list[dict] = []
    seen: set[str] = set()
    for tool in tools:
        name = tool.get("name")
        if not isinstance(name, str) or not _TOOL_NAME.match(f"{server_name}_{name}") or name in seen:
            continue
        seen.add(name)
        description = tool.get("description") if isinstance(tool.get("description"), str) else ""
        kept.append({
            "name": name,
            "description": description[:MAX_DESCRIPTION],
            "input_schema": tool.get("input_schema") or {},
            "annotations": tool.get("annotations") or None,
        })
        if len(kept) == MAX_TOOLS:
            break
    return kept


def digest(tools: list[dict]) -> str:
    """SHA-256 of the tools as the model would see them, independent of key order."""
    shown = [{k: t.get(k) for k in ("name", "description", "input_schema", "annotations")} for t in tools]
    return hashlib.sha256(json.dumps(shown, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


# What one call may add to the model's context. The rest of a result is dropped with a note saying so.
MAX_RESULT = 100_000


def cap_result(result: dict) -> dict:
    """The result as the model gets it: its content, cut at MAX_RESULT characters (an image or
    other non-text item counts by its size). `structuredContent` and `metadata` are dropped, since
    a server must also put structured content in the text, and both would be kept with the chat
    uncut."""
    kept: list[dict] = []
    used = 0
    for item in result.get("content") or []:
        size = len(item["text"]) if isinstance(item.get("text"), str) else len(repr(item))
        if used + size > MAX_RESULT:
            if isinstance(item.get("text"), str) and used < MAX_RESULT:
                kept.append({"text": item["text"][: MAX_RESULT - used]})
            kept.append({"text": f"[Echo cut this result at {MAX_RESULT} characters.]"})
            break
        kept.append(item)
        used += size
    return {"toolUseId": result.get("toolUseId"), "status": result.get("status", "error"), "content": kept}
