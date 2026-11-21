import pytest

from core.config import ConfigError, load_settings


def test_models_required():
    with pytest.raises(ConfigError, match="ECHO_MODELS"):
        load_settings({})


def test_models_must_name_a_provider():
    with pytest.raises(ConfigError, match="provider/model"):
        load_settings({"ECHO_MODELS": "anthropic/claude-sonnet-5-5, gpt-5"})


def test_defaults_and_first_model_is_default():
    s = load_settings({"ECHO_MODELS": " openai/gpt-5 , litellm/ollama/llama3 "})
    assert s.models == ("openai/gpt-5", "litellm/ollama/llama3")
    assert s.default_model == "openai/gpt-5"
    assert (s.command_timeout, s.turn_timeout) == (120, 1800)
    assert str(s.runner_socket) == "/run/echo/runner.sock"


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_bad_timeout(value):
    with pytest.raises(ConfigError, match="ECHO_TURN_TIMEOUT"):
        load_settings({"ECHO_MODELS": "openai/gpt-5", "ECHO_TURN_TIMEOUT": value})


def test_startup_fails_without_models(monkeypatch, app):
    from fastapi.testclient import TestClient

    monkeypatch.delenv("ECHO_MODELS")
    with pytest.raises(ConfigError):
        with TestClient(app):
            pass
