import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from apps.usage.repositories import usage as ledger
from tests.helpers.accounts import _run, add_key, own, sign_in_as

WS = "a" * 32


def add(client, user, at, *, agent=WS, key=None, model="claude-haiku-5-5", cost=100, tokens=10, turn=None):
    row = {
        "id": uuid.uuid4().hex, "user_id": user, "agent_id": agent, "chat_id": "c" * 32, "turn_id": turn or uuid.uuid4().hex,
        "credential_id": key, "provider": "anthropic", "model": model, "input_tokens": tokens, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_write_tokens": 0, "calls": 1, "cost_micros": cost, "at": at,
    }

    async def work(db):
        await ledger.add_rows(db, [row])

    _run(client, work)


def get(client, start="2026-11-01", end="2026-11-30", tz="UTC"):
    return client.get("/api/usage", params={"start": start, "end": end, "tz": tz})


@pytest.fixture
def app_client():
    from main import create_app

    with TestClient(create_app()) as client:
        yield client


def test_sums_a_users_own_rows_by_day_workspace_model_and_key(app_client):
    client = app_client
    other = sign_in_as(client, "bob")
    add(client, other, datetime(2026, 11, 5, tzinfo=UTC), cost=999_999)
    user = sign_in_as(client)
    own(client, user, WS)
    key = add_key(client, user)
    turn = uuid.uuid4().hex
    add(client, user, datetime(2026, 11, 5, 12, tzinfo=UTC), key=key, turn=turn)
    add(client, user, datetime(2026, 11, 5, 12, tzinfo=UTC), key=key, turn=turn, model="claude-opus-5-5", cost=400)
    add(client, user, datetime(2026, 11, 6, tzinfo=UTC), agent="d" * 32, key="gone", model="my-llama", cost=None, tokens=7)
    add(client, user, datetime(2026, 12, 1, tzinfo=UTC), cost=5)  # outside the range

    body = get(client).json()["data"]
    assert body["totals"] == {"cost_micros": 500, "input_tokens": 27, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0, "turns": 2, "unpriced_tokens": 7}
    assert len(body["days"]) == 30 and body["days"][4] == {"date": "2026-11-05", "cost_micros": 500, "tokens": 20}
    assert [(w["id"], w["name"]) for w in body["workspaces"]] == [(WS, "Test agent"), ("d" * 32, None)]
    assert [(k["id"], k["name"]) for k in body["keys"]] == [(key, "Test"), ("gone", None)]
    assert [(m["name"], m["provider"], m["cost_micros"]) for m in body["models"]][0] == ("claude-opus-5-5", "anthropic", 400)
    assert body["models"][-1]["unpriced_tokens"] == 7
    assert body["prices"]["source"].startswith("https://") and body["since"].startswith("2026-11-05")


def test_days_follow_the_asked_time_zone(app_client):
    user = sign_in_as(app_client)
    # 20:00 UTC on the 5th is already the 6th in Kolkata (UTC+5:30).
    add(app_client, user, datetime(2026, 11, 5, 20, tzinfo=UTC))
    utc = get(app_client, "2026-11-05", "2026-11-06").json()["data"]["days"]
    ist = get(app_client, "2026-11-05", "2026-11-06", "Asia/Kolkata").json()["data"]["days"]
    assert [d["cost_micros"] for d in utc] == [100, 0] and [d["cost_micros"] for d in ist] == [0, 100]


def test_nothing_counted_yet_is_an_empty_report(app_client):
    sign_in_as(app_client)
    body = get(app_client).json()["data"]
    assert body["totals"]["cost_micros"] == 0 and body["workspaces"] == [] and body["since"] is None


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"start": "2026-11-02", "end": "2026-11-01"}, "usage_range_invalid"),
        ({"start": "2025-01-01", "end": "2026-11-01"}, "usage_range_invalid"),
        ({"tz": "Mars/Olympus"}, "usage_timezone_invalid"),
        ({"tz": "../../etc/passwd"}, "usage_timezone_invalid"),
    ],
)
def test_bad_ranges_and_zones_are_400(app_client, params, code):
    sign_in_as(app_client)
    response = get(app_client, **params)
    assert response.status_code == 400 and response.json()["error"]["code"] == code


def test_needs_a_signed_in_user(app_client):
    assert get(app_client).status_code == 401
