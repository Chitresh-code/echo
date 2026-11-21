from types import SimpleNamespace

from apps.chat.services.sse import to_sse


def test_text_delta():
    assert to_sse({"data": "Hi", "delta": {}}, set()) == 'event: text\ndata: {"text": "Hi"}\n\n'


def test_tool_is_sent_once_per_id():
    seen = set()
    event = {"current_tool_use": {"toolUseId": "t1", "name": "shell", "input": '{"comm'}}
    assert to_sse(event, seen) == 'event: tool\ndata: {"id": "t1", "name": "shell"}\n\n'
    assert to_sse({**event, "current_tool_use": {**event["current_tool_use"], "input": '{"command": "ls"}'}}, seen) is None
    assert to_sse({"current_tool_use": {"toolUseId": "t2", "name": "read"}}, seen).startswith("event: tool")


def test_done():
    assert to_sse({"result": SimpleNamespace(stop_reason="end_turn")}, set()) == 'event: done\ndata: {"stopReason": "end_turn"}\n\n'


def test_everything_else_is_dropped():
    for event in [{"init_event_loop": True}, {"start": True}, {"message": {"role": "assistant"}}, {"data": None}, {"current_tool_use": {}}]:
        assert to_sse(event, set()) is None
