"""The api's settings, read once from the environment. A missing or bad value stops startup, so a
misconfigured container never serves requests."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    runner_socket: Path
    # provider/model strings a user may pick from; the first is the default.
    models: tuple[str, ...]
    command_timeout: int
    turn_timeout: int

    @property
    def default_model(self) -> str:
        return self.models[0]


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number of seconds, got {raw!r}") from None
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero, got {value}")
    return value


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    models = tuple(m.strip() for m in env.get("ECHO_MODELS", "").split(",") if m.strip())
    if not models:
        raise ConfigError("ECHO_MODELS must list at least one provider/model string, such as anthropic/claude-sonnet-5-5")
    if bad := [m for m in models if "/" not in m]:
        raise ConfigError(f"ECHO_MODELS entries must look like provider/model, got {', '.join(bad)}")
    return Settings(
        data_dir=Path(env.get("ECHO_DATA_DIR", "/data")),
        runner_socket=Path(env.get("ECHO_RUNNER_SOCKET", "/run/echo/runner.sock")),
        models=models,
        command_timeout=_positive_int(env, "ECHO_COMMAND_TIMEOUT", 120),
        turn_timeout=_positive_int(env, "ECHO_TURN_TIMEOUT", 1800),
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()
