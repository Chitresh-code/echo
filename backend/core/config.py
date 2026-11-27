"""The api's settings, read once from the environment. A missing or bad value stops startup, so a
misconfigured container never serves requests."""

import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    runner_socket: Path
    command_timeout: int
    # The runner's own cap on one command (its RUNNER_TIMEOUT_MAX), told to the agent so it asks for no more.
    command_timeout_max: int
    turn_timeout: int
    # Where users open Echo, without a trailing slash: the sign-in redirect and the only allowed Origin.
    public_url: str
    # The Entra app registration. Only users of this one tenant can sign in.
    ms_tenant_id: str
    ms_client_id: str
    # Secrets are left out of repr so a logged or printed Settings never shows them.
    ms_client_secret: str = field(repr=False)
    # A Fernet key: encrypts stored provider keys and, through a derived key, signs the sign-in cookie.
    secret_key: str = field(repr=False)
    # Workspaces one user may have. Every message from the home screen starts one, so this is set high; with the runner's per-agent disk limit this bounds a user's disk.
    max_agents: int = 50
    # Turns one user may have running at once, across all their chats.
    max_running_turns: int = 2
    # Where previews of the agents' dev servers are served, as scheme://domain[:port], each agent and
    # port on its own subdomain. None turns previews off.
    preview_url: str | None = None


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number of seconds, got {raw!r}") from None
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero, got {value}")
    return value


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def _guid(env: Mapping[str, str], name: str) -> str:
    value = _required(env, name)
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise ConfigError(f"{name} must be the GUID shown in the Entra app registration, got {value!r}") from None


def _public_url(env: Mapping[str, str]) -> str:
    value = _required(env, "ECHO_PUBLIC_URL").rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.path or parts.query or parts.fragment or parts.username:
        raise ConfigError(f"ECHO_PUBLIC_URL must be a scheme and host only, such as http://localhost:8000, got {value!r}")
    return value


def _local(host: str) -> bool:
    return host == "localhost" or host.endswith(".localhost")


def _preview_url(env: Mapping[str, str], public_url: str) -> str | None:
    value = env.get("ECHO_PREVIEW_URL", "").strip().rstrip("/")
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.path or parts.query or parts.fragment or parts.username:
        raise ConfigError(f"ECHO_PREVIEW_URL must be a scheme and domain only, such as http://preview.localhost:8000, got {value!r}")
    host, public = parts.hostname, urlsplit(public_url).hostname
    # Previews run code the agent wrote. On Echo's own host, or a parent or child of it, that code
    # could read or set Echo's cookies. Under localhost that only reaches the developer's own
    # browser, so preview.localhost next to localhost is allowed for local use.
    nested = host.endswith(f".{public}") or public.endswith(f".{host}")
    if host == public or (nested and not (_local(host) and _local(public))):
        raise ConfigError(f"ECHO_PREVIEW_URL must be a domain apart from ECHO_PUBLIC_URL's, got {value!r}")
    # The preview cookie is Secure, which browsers keep over plain http only on localhost.
    if parts.scheme == "http" and not _local(host):
        raise ConfigError(f"ECHO_PREVIEW_URL must be https unless it is under localhost, got {value!r}")
    return value.lower()


def _secret_key(env: Mapping[str, str]) -> str:
    value = _required(env, "ECHO_SECRET_KEY")
    try:
        Fernet(value)
    except ValueError:
        # Never echo the value: it is a secret even when malformed.
        raise ConfigError("ECHO_SECRET_KEY must be a Fernet key, made with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'") from None
    return value


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    command_timeout = _positive_int(env, "ECHO_COMMAND_TIMEOUT", 120)
    command_timeout_max = _positive_int(env, "ECHO_COMMAND_TIMEOUT_MAX", 1800)
    if command_timeout > command_timeout_max:
        raise ConfigError(f"ECHO_COMMAND_TIMEOUT ({command_timeout}) must not be above ECHO_COMMAND_TIMEOUT_MAX ({command_timeout_max})")
    public_url = _public_url(env)
    return Settings(
        data_dir=Path(env.get("ECHO_DATA_DIR", "/data")),
        runner_socket=Path(env.get("ECHO_RUNNER_SOCKET", "/run/echo/runner.sock")),
        command_timeout=command_timeout,
        command_timeout_max=command_timeout_max,
        turn_timeout=_positive_int(env, "ECHO_TURN_TIMEOUT", 1800),
        public_url=public_url,
        ms_tenant_id=_guid(env, "ECHO_MS_TENANT_ID"),
        ms_client_id=_guid(env, "ECHO_MS_CLIENT_ID"),
        ms_client_secret=_required(env, "ECHO_MS_CLIENT_SECRET"),
        secret_key=_secret_key(env),
        max_agents=_positive_int(env, "ECHO_MAX_AGENTS", 50),
        max_running_turns=_positive_int(env, "ECHO_MAX_RUNNING_TURNS", 2),
        preview_url=_preview_url(env, public_url),
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()
