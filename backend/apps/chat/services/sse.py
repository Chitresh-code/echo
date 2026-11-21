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
        return message("done", {"stopReason": event["result"].stop_reason})
    return None
