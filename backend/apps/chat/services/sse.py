"""Turns Strands stream events into the server-sent events a turn streams. Pure, so it is tested
with recorded events. Only what the UI shows is sent; agent internals never leave the server."""

import json


def message(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def parse(chunk: str) -> list[tuple[str, dict]]:
    """The events in what `message` wrote (one chunk may hold several), so a turn's events can be
    stored as well as streamed. Only ever reads this module's own output."""
    events = []
    for block in chunk.split("\n\n"):
        if block:
            name, data = block.split("\n", 1)
            events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def to_sse(event: dict, seen_tools: set[str]) -> str | None:
    if isinstance(event.get("data"), str):
        return message("text", {"text": event["data"]})
    if tool := event.get("current_tool_use"):
        # The tool use event repeats for every input delta; the UI only needs it once.
        tool_id = tool.get("toolUseId")
        if tool_id and tool_id not in seen_tools:
            seen_tools.add(tool_id)
            return message("tool", {"id": tool_id, "name": tool.get("name")})
        return None
    if (reply := event.get("message")) and reply.get("role") == "assistant":
        # A tool's input is complete only once the reply is, so what it acted on, the skill it
        # loaded and the plan it wrote are sent here, after its tool row.
        # A reply's text ends here, and the next reply (after tools, or once subagents finish)
        # starts a new paragraph instead of running on.
        out = [message("text", {"text": "\n\n"})] if any("text" in b for b in reply.get("content", [])) else []
        for use in _tool_uses(reply):
            if text := detail(use.get("input")):
                out.append(message("tool_detail", {"id": use["toolUseId"], "detail": text}))
            if use.get("name") == "skills":
                out.append(message("skill", {"id": use["toolUseId"], "name": _skill_name(use)}))
            elif use.get("name") == "todo_write" and (items := todo_items(use.get("input"))) is not None:
                out.append(message("todos", {"items": items}))
        return "".join(out) or None
    if (reply := event.get("message")) and reply.get("role") == "user":
        results = [b["toolResult"] for b in reply.get("content", []) if "toolResult" in b]
        return "".join(message("tool_result", {"id": r.get("toolUseId"), "ok": r.get("status") == "success"}) for r in results) or None
    return None


# The input keys that say what a call acted on, most telling first.
DETAIL_KEYS = ("command", "path", "url", "task", "skill_name", "pattern", "name")


def detail(tool_input) -> str:
    """What a tool call acted on, short enough for one row. The model wrote the input, so it may
    not be the shape the tool asked for."""
    if isinstance(tool_input, dict):
        for key in DETAIL_KEYS:
            if isinstance(value := tool_input.get(key), str) and value:
                return value[:200]
    return ""


TODO_STATUSES = ("pending", "in_progress", "completed")


def todo_items(tool_input) -> list[dict] | None:
    """The plan a todo_write call wrote, cut to what one checklist shows."""
    todos = tool_input.get("todos") if isinstance(tool_input, dict) else None
    if not isinstance(todos, list):
        return None
    items = []
    for todo in todos[:30]:
        if not isinstance(todo, dict):
            continue
        status = todo.get("status") if todo.get("status") in TODO_STATUSES else "pending"
        text = todo.get("activeForm") if status == "in_progress" and todo.get("activeForm") else todo.get("content")
        items.append({"text": str(text or "")[:200], "status": status})
    return items


def done_data(result, extra_usage: dict[str, int] | None = None) -> dict:
    usage = usage_of(result)
    for key in USAGE_KEYS:
        usage[key] += (extra_usage or {}).get(key, 0)
    return {"stopReason": result.stop_reason, "usage": usage}


USAGE_KEYS = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheWriteInputTokens")


def usage_of(result) -> dict[str, int]:
    """The turn's tokens on the chosen model, so users see what it cost them. Page summaries and
    memory extraction run on a separate small model and are not counted here; subagents' tokens
    are added by the caller."""
    usage = result.metrics.accumulated_usage
    return {key: usage.get(key, 0) for key in USAGE_KEYS}


def _tool_uses(reply: dict) -> list[dict]:
    return [b["toolUse"] for b in reply.get("content", []) if "toolUse" in b]


def _skill_name(use: dict) -> str:
    # The model wrote this input, so it may not be the shape the tool asked for.
    value = use.get("input")
    return str(value.get("skill_name", ""))[:64] if isinstance(value, dict) else ""
