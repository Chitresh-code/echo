"""The keys API with the provider check stubbed: what is stored, what is shown, and who can use it."""

import sqlite3

import pytest

from apps.credentials.models.credential import ProviderModel
from apps.credentials.services import credential_service, crypto
from apps.accounts.services.session_service import COOKIE
from core.config import get_settings
from core.db import db_path
from core.errors import AppError
from tests.helpers.accounts import sign_in_as

KEY = "sk-ant-the-real-secret-key-9xYz"
MODELS = [ProviderModel(id="claude-sonnet-5-5", name="Claude Sonnet 5.5")]


@pytest.fixture
def provider(monkeypatch):
    """Records each check and answers with MODELS, or raises `provider.error` when set."""

    class State:
        calls: list[tuple] = []
        error: AppError | None = None

    async def list_models(name, key, base_url):
        State.calls.append((name, key, base_url))
        if State.error:
            raise State.error
        return MODELS

    async def check_chat(key, base_url, model):
        State.calls.append(("chat", key, base_url, model))
        if State.error:
            raise State.error

    monkeypatch.setattr(credential_service.providers, "list_models", list_models)
    monkeypatch.setattr(credential_service.providers, "check_chat", check_chat)
    return State


def add(client, **body):
    return client.post("/api/credentials", json={"provider": "anthropic", "label": "Work", "api_key": KEY, **body})


def test_add_checks_the_key_and_never_shows_or_stores_it_plainly(client, provider):
    sign_in_as(client)
    r = add(client)
    assert r.status_code == 200 and provider.calls == [("anthropic", KEY, None)]
    credential = r.json()["data"]
    assert credential["key_hint"] == "9xYz" and credential["provider"] == "anthropic" and credential["base_url"] is None
    listed = client.get("/api/credentials")
    models = client.get(f"/api/credentials/{credential['id']}/models")
    assert models.json()["data"] == [{"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5"}]
    assert provider.calls[-1] == ("anthropic", KEY, None)
    for response in (r, listed, models):
        assert KEY not in response.text and "the-real-secret" not in response.text

    with sqlite3.connect(db_path(get_settings().data_dir)) as db:
        row = db.execute("select key_encrypted, key_hint from credentials").fetchone()
        dump = "\n".join(db.iterdump())
    assert KEY not in dump and KEY.encode() not in row[0]
    assert crypto.decrypt(get_settings(), row[0]) == KEY


def test_a_key_cannot_be_read_under_another_secret(client, provider, monkeypatch):
    token = crypto.encrypt(get_settings(), KEY)
    monkeypatch.setenv("ECHO_SECRET_KEY", "b3RoZXItdGVzdC1rZXktbm90LWEtc2VjcmV0LTAwMDA=")
    get_settings.cache_clear()
    with pytest.raises(AppError) as raised:
        crypto.decrypt(get_settings(), token)
    assert raised.value.code == "credential_unreadable"


def test_a_short_key_gets_no_hint(client, provider):
    sign_in_as(client)
    assert add(client, api_key="sk-short").json()["data"]["key_hint"] == ""


def test_a_refused_key_is_not_stored(client, provider):
    sign_in_as(client)
    provider.error = AppError(400, "invalid_key", "The provider did not accept this key.")
    r = add(client)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_key")
    assert client.get("/api/credentials").json()["data"] == []


@pytest.mark.parametrize("body", [
    {"provider": "openai_compatible"},
    {"provider": "openai_compatible", "base_url": "http://api.example.com/v1"},
    {"provider": "openai_compatible", "base_url": "https://u:p@api.example.com"},
    {"provider": "openai", "base_url": "https://api.example.com/v1"},
])
def test_bad_base_urls_are_refused_before_the_provider_is_called(client, provider, body):
    sign_in_as(client)
    r = add(client, **body)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_base_url") and provider.calls == []


def test_a_custom_endpoint_is_stored_with_its_base_url(client, provider):
    sign_in_as(client)
    r = add(client, provider="openai_compatible", base_url="https://api.example.com/v1/")
    assert r.json()["data"]["base_url"] == "https://api.example.com/v1"
    assert provider.calls == [("openai_compatible", KEY, "https://api.example.com/v1")]


def test_unknown_provider_is_422(client, provider):
    sign_in_as(client)
    r = add(client, provider="ollama")
    assert r.status_code == 422 and KEY not in r.text


def test_a_user_cannot_see_use_or_delete_another_users_key(client, provider):
    sign_in_as(client, "ada")
    credential_id = add(client).json()["data"]["id"]
    ada = client.cookies[COOKIE]

    sign_in_as(client, "bob")
    provider.calls = []
    assert client.get("/api/credentials").json()["data"] == []
    for method, path in [("GET", f"/api/credentials/{credential_id}/models"), ("DELETE", f"/api/credentials/{credential_id}")]:
        r = client.request(method, path)
        assert (r.status_code, r.json()["error"]["code"]) == (404, "credential_not_found"), f"{method} {path}"
    assert provider.calls == []

    client.cookies.set(COOKIE, ada)
    assert len(client.get("/api/credentials").json()["data"]) == 1
    assert client.delete(f"/api/credentials/{credential_id}").json()["data"] == {"deleted": True}
    assert client.get("/api/credentials").json()["data"] == []


def test_a_compatible_key_with_models_is_checked_by_chat_and_lists_them(client, provider):
    sign_in_as(client)
    r = add(client, provider="openai_compatible", base_url="https://gw.example.com/v1", models=["gpt-5.4-mini", "other", "gpt-5.4-mini"])
    credential = r.json()["data"]
    assert credential["models"] == ["gpt-5.4-mini", "other"]
    assert provider.calls == [("chat", KEY, "https://gw.example.com/v1", "gpt-5.4-mini")]
    models = client.get(f"/api/credentials/{credential['id']}/models").json()["data"]
    assert models == [{"id": "gpt-5.4-mini", "name": "gpt-5.4-mini"}, {"id": "other", "name": "other"}]
    assert len(provider.calls) == 1  # the stored list is served without calling the endpoint
    assert client.get("/api/credentials").json()["data"][0]["models"] == ["gpt-5.4-mini", "other"]


def test_a_key_without_models_shows_null(client, provider):
    sign_in_as(client)
    assert add(client).json()["data"]["models"] is None


@pytest.mark.parametrize("body, status, code", [
    ({"models": ["claude-sonnet-5-5"]}, 400, "models_not_supported"),
    ({"provider": "openai_compatible", "base_url": "https://gw.example.com/v1", "models": []}, 422, "validation_error"),
    ({"provider": "openai_compatible", "base_url": "https://gw.example.com/v1", "models": ["has space"]}, 422, "validation_error"),
    ({"provider": "openai_compatible", "base_url": "https://gw.example.com/v1", "models": ["m"] * 51}, 422, "validation_error"),
])
def test_bad_model_lists_are_refused_before_the_provider_is_called(client, provider, body, status, code):
    sign_in_as(client)
    r = add(client, **body)
    assert (r.status_code, r.json()["error"]["code"]) == (status, code) and provider.calls == []


def test_a_failed_chat_check_stores_nothing(client, provider):
    sign_in_as(client)
    provider.error = AppError(400, "model_not_available", "The endpoint does not serve the model x.")
    r = add(client, provider="openai_compatible", base_url="https://gw.example.com/v1", models=["x"])
    assert (r.status_code, r.json()["error"]["code"]) == (400, "model_not_available")
    assert client.get("/api/credentials").json()["data"] == []
