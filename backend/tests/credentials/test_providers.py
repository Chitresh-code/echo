import anthropic
import httpx
import httpx2
import openai
import pytest
from google.genai import errors as genai_errors
from strands.models.anthropic import AnthropicModel
from strands.models.gemini import GeminiModel
from strands.models.openai_responses import OpenAIResponsesModel

from apps.credentials.services import providers
from core.errors import AppError

KEY = "sk-user-key-0123456789"


def test_each_provider_builds_its_model_with_the_users_key():
    model = providers.build_model("anthropic", KEY, None, "claude-sonnet-5-5")
    assert isinstance(model, AnthropicModel) and model.client.api_key == KEY
    assert model.config["model_id"] == "claude-sonnet-5-5" and model.config["max_tokens"] > 0

    model = providers.build_model("openai", KEY, None, "gpt-5")
    assert isinstance(model, OpenAIResponsesModel) and model.client_args == {"api_key": KEY}

    model = providers.build_model("google", KEY, None, "gemini-2.5-flash")
    assert isinstance(model, GeminiModel) and model.client_args == {"api_key": KEY}

    model = providers.build_model("openai_compatible", KEY, "https://api.example.com/v1", "m")
    assert model.client_args == {"api_key": KEY, "base_url": "https://api.example.com/v1"}


@pytest.mark.parametrize("provider", ["anthropic", "openai", "google"])
def test_side_model_is_small_without_reasoning_or_search_on_the_same_key(provider):
    side = providers.build_side_model(provider, KEY, None, main=None)
    assert side.config["model_id"] == providers.SIDE_MODELS[provider]
    config = str(side.config)
    assert "web_search" not in config and "google_search" not in config and "thinking" not in config
    assert getattr(side, "client_args", None) == {"api_key": KEY} or side.client.api_key == KEY


def test_side_model_of_a_compatible_endpoint_is_the_turns_model():
    main = providers.build_model("openai_compatible", KEY, "https://api.example.com/v1", "m")
    assert providers.build_side_model("openai_compatible", KEY, "https://api.example.com/v1", main) is main


@pytest.mark.parametrize("provider, model_id, effort, params", [
    ("anthropic", "claude-sonnet-5-5", "high", {"thinking": {"type": "adaptive", "display": "summarized"}, "output_config": {"effort": "high"}}),
    ("openai", "gpt-6-luna", "off", {"reasoning": {"effort": "none"}}),
    ("openai", "gpt-6-luna", "auto", {"reasoning": {"effort": "high"}}),
    ("google", "gemini-2.5-flash", "low", {"thinking_config": {"thinking_level": "low"}}),
])
def test_effort_reaches_the_providers_setting(provider, model_id, effort, params):
    config = providers.build_model(provider, KEY, None, model_id, effort).config["params"]
    assert params.items() <= config.items()


def test_unsupported_effort_is_refused_with_the_supported_levels():
    with pytest.raises(AppError) as e:
        providers.build_model("google", KEY, None, "gemini-2.5-flash", "max")
    assert e.value.status_code == 400 and e.value.code == "effort_not_supported" and "low, medium, high" in e.value.message


def test_openai_compatible_takes_only_auto():
    assert providers.build_model("openai_compatible", KEY, "https://api.example.com/v1", "m", "auto")
    with pytest.raises(AppError) as e:
        providers.build_model("openai_compatible", KEY, "https://api.example.com/v1", "m", "high")
    assert e.value.code == "effort_not_supported"


def status_error(module, http, cls, status):
    response = http.Response(status, request=http.Request("GET", "https://provider.example"))
    return getattr(module, cls)("provider says: key sk-leak is bad", response=response, body=None)


@pytest.mark.parametrize("exc", [
    status_error(openai, httpx, "AuthenticationError", 401),
    status_error(openai, httpx, "PermissionDeniedError", 403),
    status_error(anthropic, httpx2, "AuthenticationError", 401),
    genai_errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid sk-leak", "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}}),
])
def test_a_refused_key_is_invalid_key_without_the_providers_text(exc):
    error = providers.provider_error(exc)
    assert (error.status_code, error.code) == (400, "invalid_key") and "sk-leak" not in error.message


@pytest.mark.parametrize("exc", [
    status_error(openai, httpx, "InternalServerError", 500),
    genai_errors.ClientError(429, {"error": {"code": 429, "message": "quota sk-leak", "status": "RESOURCE_EXHAUSTED"}}),
    RuntimeError("sk-leak"),
])
def test_anything_else_is_provider_error_without_its_text(exc):
    error = providers.provider_error(exc)
    assert (error.status_code, error.code) == (502, "provider_error") and "sk-leak" not in error.message
