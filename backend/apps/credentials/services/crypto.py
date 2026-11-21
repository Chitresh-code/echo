"""Provider keys are stored encrypted with ECHO_SECRET_KEY (Fernet: AES with an HMAC), so a copy of
the database alone does not give away anyone's keys."""

from cryptography.fernet import Fernet, InvalidToken

from core.config import Settings
from core.errors import AppError


# shortcut: one key and no rotation, so changing ECHO_SECRET_KEY loses every stored key; add a re-encrypt command with MultiFernet when the secret must change.
def encrypt(settings: Settings, key: str) -> bytes:
    return Fernet(settings.secret_key).encrypt(key.encode())


def decrypt(settings: Settings, token: bytes) -> str:
    try:
        return Fernet(settings.secret_key).decrypt(token).decode()
    except InvalidToken:
        # The server's secret key changed since this key was stored.
        raise AppError(500, "credential_unreadable", "This key can no longer be read. Delete it and add it again.") from None
