"""Chats from before chats were stored are rebuilt from a recorded harness snapshot."""

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from apps.chat.services.legacy_import import SNAPSHOT, turns_from
from core.config import get_settings
from tests.helpers.accounts import own, sign_in_as

FIXTURE = Path(__file__).parent.parent / "fixtures" / "harness_snapshot.json"
WS, CHAT, GONE = "a" * 32, "b" * 32, "9" * 32


def test_a_recorded_session_becomes_one_turn_that_replays_like_the_stream():
    [turn] = turns_from(json.loads(FIXTURE.read_text())["data"]["messages"])
    assert turn["prompt"].startswith("Create [**hello.py**]") and "system-reminder" not in turn["prompt"]
    kinds = [e for e, _ in turn["events"]]
    assert kinds.count("tool") == 2 and kinds.count("tool_result") == 2 and kinds.count("tool_detail") == 2
    assert all(d["ok"] for e, d in turn["events"] if e == "tool_result")
    text = "".join(d["text"] for e, d in turn["events"] if e == "text")
    assert text.strip().startswith("Created `hello.py`")


def place(agent_id, chat_id, body):
    folder = get_settings().data_dir / "sessions" / agent_id / "session" / chat_id / SNAPSHOT
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.write_text(body)


def test_older_chats_are_imported_once_and_bad_folders_are_skipped(fake_runner, caplog):
    from main import create_app

    with TestClient(create_app()) as client:
        user = sign_in_as(client)
        own(client, user, WS)
        cookies = dict(client.cookies)
    place(WS, CHAT, FIXTURE.read_text())
    place(WS, "c" * 32, "{not json")
    place(GONE, CHAT, FIXTURE.read_text())
    for _ in range(2):
        with TestClient(create_app()) as client:
            client.cookies.update(cookies)
            listed = client.get(f"/api/agents/{WS}/chats").json()["data"]["chats"]
            assert [c["id"] for c in listed] == [CHAT] and listed[0]["title"].startswith("Create hello.py that prints hello")
            [turn] = client.get(f"/api/agents/{WS}/chats/{CHAT}").json()["data"]["turns"]
            assert turn["status"] == "done" and turn["usage"] is None and turn["events"]
    assert "Could not import the older chat" in caplog.text
