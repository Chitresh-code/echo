from types import SimpleNamespace

from apps.chat.services.sse import done_data, to_sse


def test_text_delta():
    assert to_sse({"data": "Hi", "delta": {}}, set()) == 'event: text\ndata: {"text": "Hi"}\n\n'


def test_tool_is_sent_once_per_id():
    seen = set()
    event = {"current_tool_use": {"toolUseId": "t1", "name": "shell", "input": '{"comm'}}
    assert to_sse(event, seen) == 'event: tool\ndata: {"id": "t1", "name": "shell"}\n\n'
    assert to_sse({**event, "current_tool_use": {**event["current_tool_use"], "input": '{"command": "ls"}'}}, seen) is None
    assert to_sse({"current_tool_use": {"toolUseId": "t2", "name": "read"}}, seen).startswith("event: tool")


def test_done_carries_the_turns_token_usage():
    result = SimpleNamespace(stop_reason="end_turn", metrics=SimpleNamespace(accumulated_usage={"inputTokens": 900, "outputTokens": 40, "totalTokens": 940, "cacheReadInputTokens": 600}))
    assert done_data(result) == {
        "stopReason": "end_turn",
        "usage": {"inputTokens": 900, "outputTokens": 40, "cacheReadInputTokens": 600, "cacheWriteInputTokens": 0},
    }


def test_everything_else_is_dropped():
    for event in [{"init_event_loop": True}, {"start": True}, {"message": {"role": "assistant"}}, {"data": None}, {"current_tool_use": {}}]:
        assert to_sse(event, set()) is None


def test_a_finished_skills_call_names_the_skill():
    reply = {"role": "assistant", "content": [
        {"text": "Loading it."},
        {"toolUse": {"toolUseId": "t1", "name": "skills", "input": {"skill_name": "weekly-report"}}},
        {"toolUse": {"toolUseId": "t2", "name": "shell", "input": {"command": "ls"}}},
        {"toolUse": {"toolUseId": "t3", "name": "skills", "input": "not json"}},
    ]}
    assert to_sse({"message": reply}, set()) == (
        'event: skill\ndata: {"id": "t1", "name": "weekly-report"}\n\n'
        'event: skill\ndata: {"id": "t3", "name": ""}\n\n'
    )
    assert to_sse({"message": {"role": "user", "content": [{"toolUse": {"toolUseId": "t1", "name": "skills"}}]}}, set()) is None
