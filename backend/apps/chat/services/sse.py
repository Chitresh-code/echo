"""Turns Strands stream events into the server-sent events a turn streams. Pure, so it is tested
with recorded events. Only what the UI shows is sent; agent internals never leave the server."""

import json


def message(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


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
        # The skills tool's input is complete only once the reply is, so the skill it loaded is
        # named here, after its tool row.
        used = [message("skill", {"id": use["toolUseId"], "name": _skill_name(use)}) for use in _tool_uses(reply, "skills")]
        return "".join(used) or None
    return None


def done_data(result) -> dict:
    return {"stopReason": result.stop_reason, "usage": usage_of(result)}


USAGE_KEYS = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheWriteInputTokens")


def usage_of(result) -> dict[str, int]:
    """The turn's tokens on the chosen model, so users see what it cost them. Page summaries and
    memory extraction run on a separate small model and are not counted here."""
    usage = result.metrics.accumulated_usage
    return {key: usage.get(key, 0) for key in USAGE_KEYS}


def _tool_uses(reply: dict, name: str) -> list[dict]:
    return [b["toolUse"] for b in reply.get("content", []) if b.get("toolUse", {}).get("name") == name]


def _skill_name(use: dict) -> str:
    # The model wrote this input, so it may not be the shape the tool asked for.
    value = use.get("input")
    return str(value.get("skill_name", ""))[:64] if isinstance(value, dict) else ""
