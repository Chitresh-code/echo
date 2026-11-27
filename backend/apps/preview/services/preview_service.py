"""Signed proof that a user may see one agent's port: a start token that lives a minute, handed out
by the api, and the cookie the preview host sets from it."""

from itsdangerous import BadData, URLSafeTimedSerializer

from core.config import Settings
from core.errors import AppError

COOKIE = "echo_preview"
START_PATH = "/.echo-preview/start"
TOKEN_SECONDS = 60
COOKIE_SECONDS = 8 * 3600


def _signer(settings: Settings, use: str) -> URLSafeTimedSerializer:
    # itsdangerous derives a key per salt, so a start token never passes as a cookie or the other way
    # round, and neither shares a key with the encryption of provider keys.
    return URLSafeTimedSerializer(settings.secret_key, salt=f"echo preview {use}")


def origin(settings: Settings, agent_id: str, port: int) -> str:
    scheme, _, domain = settings.preview_url.partition("://")
    return f"{scheme}://{agent_id}-{port}.{domain}"


def start_url(settings: Settings, user_id: str, agent_id: str, port: int) -> str:
    if not settings.preview_url:
        raise AppError(404, "preview_off", "Previews are not set up on this Echo.")
    token = _signer(settings, "start").dumps({"u": user_id, "a": agent_id, "p": port})
    return f"{origin(settings, agent_id, port)}{START_PATH}?token={token}"


def cookie_value(settings: Settings, user_id: str, agent_id: str, port: int) -> str:
    return _signer(settings, "cookie").dumps({"u": user_id, "a": agent_id, "p": port})


def user_for(settings: Settings, use: str, value: str | None, agent_id: str, port: int) -> str | None:
    """The user a start token or cookie was signed for, if it is good, young enough and for this
    agent and port; otherwise None."""
    if not value:
        return None
    try:
        data = _signer(settings, use).loads(value, max_age=TOKEN_SECONDS if use == "start" else COOKIE_SECONDS)
    except BadData:
        return None
    if not isinstance(data, dict) or data.get("a") != agent_id or data.get("p") != port or not isinstance(data.get("u"), str):
        return None
    return data["u"]
