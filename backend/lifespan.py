import logging
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI
from strands_harness.models import resolve_model

from core.config import get_settings
from sandbox.runner_sandbox import raise_for_runner_error, runner_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at startup, not on the first request, when the environment or the data volume is wrong.
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=settings.data_dir):
        pass
    # Building a model needs no key or network call, but it fails for an unknown provider or a
    # provider whose SDK is not installed, which would otherwise surface on the first turn.
    for model in settings.models:
        try:
            resolve_model(model, model)
        except Exception as exc:
            raise RuntimeError(f"ECHO_MODELS entry {model} cannot be used: {exc}") from exc
    # Nothing works without the runner, so a missing or unanswering socket stops startup.
    try:
        async with runner_client(settings.runner_socket) as client:
            await raise_for_runner_error(await client.get("/health"))
    except Exception as exc:
        raise RuntimeError(f"The runner at {settings.runner_socket} did not answer its health check") from exc
    logger.info("Echo api started with models %s", ", ".join(settings.models))
    yield
