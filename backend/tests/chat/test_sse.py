from types import SimpleNamespace

from apps.chat.services.sse import detail, done_data, to_sse, todo_items


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


def test_a_finished_reply_with_text_ends_its_paragraph():
    assert to_sse({"message": {"role": "assistant", "content": [{"text": "Started them."}]}}, set()) == 'event: text\ndata: {"text": "\\n\\n"}\n\n'


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
        'event: text\ndata: {"text": "\\n\\n"}\n\n'
        'event: tool_detail\ndata: {"id": "t1", "detail": "weekly-report"}\n\n'
        'event: skill\ndata: {"id": "t1", "name": "weekly-report"}\n\n'
        'event: tool_detail\ndata: {"id": "t2", "detail": "ls"}\n\n'
        'event: skill\ndata: {"id": "t3", "name": ""}\n\n'
    )
    assert to_sse({"message": {"role": "user", "content": [{"toolUse": {"toolUseId": "t1", "name": "skills"}}]}}, set()) is None


def test_detail_takes_the_most_telling_input():
    assert detail({"path": "a.py", "command": "ls"}) == "ls"
    assert detail({"url": "https://x"}) == "https://x"
    assert detail({"command": "x" * 500}) == "x" * 200
    assert detail({"command": 3, "content": "secret"}) == ""
    assert detail("not json") == "" and detail(None) == ""


def test_tool_results_say_whether_each_call_succeeded():
    reply = {"role": "user", "content": [
        {"toolResult": {"toolUseId": "t1", "status": "success", "content": [{"text": "big output"}]}},
        {"toolResult": {"toolUseId": "t2", "status": "error", "content": []}},
    ]}
    out = to_sse({"message": reply}, set())
    assert out == 'event: tool_result\ndata: {"id": "t1", "ok": true}\n\nevent: tool_result\ndata: {"id": "t2", "ok": false}\n\n'
    assert "big output" not in out


def test_a_plan_is_sent_cut_to_size():
    todos = [
        {"content": "Read", "activeForm": "Reading", "status": "completed"},
        {"content": "Fix", "activeForm": "Fixing", "status": "in_progress"},
        {"content": "y" * 300, "status": "weird"},
        "not a dict",
    ] + [{"content": "more", "status": "pending"}] * 40
    items = todo_items({"todos": todos})
    assert items[:3] == [{"text": "Read", "status": "completed"}, {"text": "Fixing", "status": "in_progress"}, {"text": "y" * 200, "status": "pending"}]
    assert len(items) == 29  # 30 entries looked at, one dropped
    assert todo_items({"todos": "x"}) is None and todo_items(None) is None
    reply = {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t1", "name": "todo_write", "input": {"todos": todos[:2]}}}]}
    assert to_sse({"message": reply}, set()) == 'event: todos\ndata: {"items": [{"text": "Read", "status": "completed"}, {"text": "Fixing", "status": "in_progress"}]}\n\n'


def test_done_adds_the_subagents_tokens():
    result = SimpleNamespace(stop_reason="end_turn", metrics=SimpleNamespace(accumulated_usage={"inputTokens": 100, "outputTokens": 10}))
    assert done_data(result, {"inputTokens": 50, "outputTokens": 5, "cacheReadInputTokens": 7, "totalTokens": 62})["usage"] == {
        "inputTokens": 150, "outputTokens": 15, "cacheReadInputTokens": 7, "cacheWriteInputTokens": 0,
    }
