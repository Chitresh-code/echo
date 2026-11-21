"""Per provider: list the models a key can use, build the Strands model a turn runs on, and turn
provider errors into fixed messages. A provider's error text never reaches the caller: it can quote
the request, and it is the provider's wording, not Echo's."""

import contextlib
import logging

import anthropic
import openai
from google import genai
from strands.models import Model
from strands.models.openai import OpenAIModel
from strands_harness.models import resolve_model

from apps.credentials.models.credential import ProviderModel
from apps.credentials.services import safe_http
from core.errors import AppError

logger = logging.getLogger(__name__)

TIMEOUT = 30.0
# shortcut: a custom endpoint's model list is capped, not paged; page it if an endpoint really serves more.
MAX_MODELS = 1000


class _GuardedOpenAIModel(OpenAIModel):
    """Chat Completions against a custom endpoint, through the address-checking client. Strands
    builds a fresh OpenAI client for each request and closes it after, so the guarded httpx client
    is made fresh each time too rather than passed in once and closed after the first call."""

    @contextlib.asynccontextmanager
    async def _get_client(self):
        async with openai.AsyncOpenAI(**self.client_args, http_client=safe_http.client()) as client:
            yield client


def build_model(provider: str, api_key: str, base_url: str | None, model_id: str, effort: str = "auto", web_search: bool = True) -> Model:
    if provider == "openai_compatible":
        # Echo cannot know which reasoning parameter, if any, an arbitrary endpoint accepts, and an
        # unknown one can fail the whole request.
        if effort != "auto":
            raise AppError(400, "effort_not_supported", "OpenAI-compatible endpoints take only effort 'auto'.")
        return _GuardedOpenAIModel(client_args={"api_key": api_key, "base_url": base_url}, model_id=model_id)
    # The harness's own builders, so turns keep its per-model output limits, prompt caching, native
    # web search and reasoning. They read keys from the environment, which holds none, so the
    # user's key is set on the model's client before any request.
    try:
        model = resolve_model(f"{provider}/{model_id}", default="", effort=effort, web_search=web_search, caching=provider == "anthropic")
    except ValueError as exc:
        # The harness's own check of the level against the model, which names the supported levels.
        raise AppError(400, "effort_not_supported", str(exc)) from None
    if provider == "anthropic":
        model.client = anthropic.AsyncAnthropic(api_key=api_key)
    else:
        model.client_args = {"api_key": api_key}
    return model


# Small models for page summaries and memory extraction, which otherwise run on the turn's own
# model and effort. Each must be in the provider's model list for an ordinary key.
# shortcut: one fixed id per provider, so a key without access to it loses page summaries and memory extraction (logged); make it a per-user setting if that is reported.
SIDE_MODELS = {"anthropic": "claude-haiku-5-5", "openai": "gpt-6-luna", "google": "gemini-3.5-flash-lite"}


def build_side_model(provider: str, api_key: str, base_url: str | None, main: Model) -> Model:
    """The model for the agent's side work: small, no reasoning, on the same key. An
    openai_compatible endpoint serves its own models, so it keeps the turn's model."""
    if provider not in SIDE_MODELS:
        return main
    return build_model(provider, api_key, base_url, SIDE_MODELS[provider], effort="off", web_search=False)


async def list_models(provider: str, api_key: str, base_url: str | None) -> list[ProviderModel]:
    """The models the key can use, which also proves the key works."""
    try:
        if provider == "anthropic":
            async with anthropic.AsyncAnthropic(api_key=api_key, timeout=TIMEOUT, max_retries=0) as client:
                return [ProviderModel(id=m.id, name=m.display_name) async for m in client.models.list(limit=1000)]
        if provider == "google":
            client = genai.Client(api_key=api_key)
            try:
                return [
                    ProviderModel(id=m.name.removeprefix("models/"), name=m.display_name or m.name)
                    async for m in await client.aio.models.list()
                    if "generateContent" in (m.supported_actions or [])
                ]
            finally:
                await client.aio.aclose()
        extra = {"base_url": base_url, "http_client": safe_http.client()} if provider == "openai_compatible" else {}
        async with openai.AsyncOpenAI(api_key=api_key, timeout=TIMEOUT, max_retries=0, **extra) as client:
            models = []
            async for m in client.models.list():
                models.append(ProviderModel(id=m.id, name=m.id))
                if len(models) >= MAX_MODELS:
                    break
            return sorted(models, key=lambda m: m.id)
    except Exception as exc:
        raise provider_error(exc) from None


def provider_error(exc: Exception) -> AppError:
    if safe_http.refused(exc):
        return AppError(400, "endpoint_not_allowed", "The endpoint's address is local or private, and Echo only calls public addresses.")
    status = None
    if isinstance(exc, (anthropic.APIStatusError, openai.APIStatusError)):
        status = exc.status_code
    elif isinstance(exc, genai.errors.APIError):
        # Google answers a bad key with 400 API_KEY_INVALID rather than 401.
        status = 401 if "API_KEY_INVALID" in str(exc.details) else exc.code
    if status in (401, 403):
        return AppError(400, "invalid_key", "The provider did not accept this key.")
    # The log formatter masks anything that looks like a key in the provider's text.
    logger.warning("Provider call failed: %s: %s", type(exc).__name__, exc)
    return AppError(502, "provider_error", "The provider could not be reached or returned an error.")
