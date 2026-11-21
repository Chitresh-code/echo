import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.config import get_settings
from core.db import create_engine, migrate
from sandbox.runner_sandbox import raise_for_runner_error, runner_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at startup, not on the first request, when the environment or the data volume is wrong.
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=settings.data_dir):
        pass
    # Migrating before serving means no request ever sees an old schema.
    await asyncio.to_thread(migrate, settings.data_dir)
    # Models now come from each user's own keys; an old deployment's setting would otherwise look like it still did something.
    if "ECHO_MODELS" in os.environ:
        logger.warning("ECHO_MODELS is set but ignored: each user picks a model from their own provider keys")
    # Nothing works without the runner, so a missing or unanswering socket stops startup.
    try:
        async with runner_client(settings.runner_socket) as client:
            await raise_for_runner_error(await client.get("/health"))
    except Exception as exc:
        raise RuntimeError(f"The runner at {settings.runner_socket} did not answer its health check") from exc
    logger.info("Echo api started")
    app.state.db_engine = create_engine(settings.data_dir)
    try:
        yield
    finally:
        await app.state.db_engine.dispose()
