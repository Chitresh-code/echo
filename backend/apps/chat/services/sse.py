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
    if "result" in event:
        result = event["result"]
        return message("done", {"stopReason": result.stop_reason, "usage": usage_of(result)})
    return None


USAGE_KEYS = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheWriteInputTokens")


def usage_of(result) -> dict[str, int]:
    """The turn's tokens on the chosen model, so users see what it cost them. Page summaries and
    memory extraction run on a separate small model and are not counted here."""
    usage = result.metrics.accumulated_usage
    return {key: usage.get(key, 0) for key in USAGE_KEYS}
