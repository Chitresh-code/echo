import pytest

from core.config import ConfigError, load_settings
from tests.conftest import TEST_ENV

BASE = dict(TEST_ENV)


def test_defaults():
    s = load_settings(BASE)
    assert (s.command_timeout, s.command_timeout_max, s.turn_timeout) == (120, 1800, 1800)
    assert str(s.runner_socket) == "/run/echo/runner.sock"


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_bad_timeout(value):
    with pytest.raises(ConfigError, match="ECHO_TURN_TIMEOUT"):
        load_settings({**BASE, "ECHO_TURN_TIMEOUT": value})


def test_command_timeout_must_fit_the_runner_cap():
    with pytest.raises(ConfigError, match="ECHO_COMMAND_TIMEOUT_MAX"):
        load_settings({**BASE, "ECHO_COMMAND_TIMEOUT": "600", "ECHO_COMMAND_TIMEOUT_MAX": "300"})


def test_old_models_setting_is_ignored_with_a_warning(monkeypatch, app, fake_runner, caplog):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("ECHO_MODELS", "anthropic/claude-sonnet-5-5")
    with TestClient(app):
        pass
    assert "ECHO_MODELS is set but ignored" in caplog.text


@pytest.mark.parametrize("name", list(TEST_ENV))
def test_account_settings_required(name):
    with pytest.raises(ConfigError, match=name):
        load_settings({**BASE, name: ""})


@pytest.mark.parametrize("name,value", [
    ("ECHO_PUBLIC_URL", "localhost:8000"),
    ("ECHO_PUBLIC_URL", "ftp://example.com"),
    ("ECHO_PUBLIC_URL", "https://example.com/echo"),
    ("ECHO_PUBLIC_URL", "https://user@example.com"),
    ("ECHO_MS_TENANT_ID", "contoso.onmicrosoft.com"),
    ("ECHO_MS_CLIENT_ID", "not-a-guid"),
    ("ECHO_SECRET_KEY", "too-short-secret"),
])
def test_bad_account_settings(name, value):
    with pytest.raises(ConfigError, match=name):
        load_settings({**BASE, name: value})


def test_bad_secret_key_is_not_echoed():
    with pytest.raises(ConfigError) as caught:
        load_settings({**BASE, "ECHO_SECRET_KEY": "hunter2-is-my-secret"})
    assert "hunter2" not in str(caught.value)


def test_account_settings_and_secrets_hidden_from_repr():
    s = load_settings({**BASE, "ECHO_PUBLIC_URL": "https://echo.example.com/"})
    assert s.public_url == "https://echo.example.com"
    assert TEST_ENV["ECHO_SECRET_KEY"] not in repr(s) and TEST_ENV["ECHO_MS_CLIENT_SECRET"] not in repr(s)
