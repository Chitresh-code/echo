"""Microsoft Entra sign-in for one tenant: authorization code with PKCE through Authlib."""

import hashlib
import hmac
from functools import lru_cache

from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App

from core.config import Settings
from core.errors import AppError


def issuer(settings: Settings) -> str:
    return f"https://login.microsoftonline.com/{settings.ms_tenant_id}/v2.0"


def state_cookie_key(settings: Settings) -> str:
    # A key derived for this one use, so the cookie signature never shares a key with the encryption of provider keys.
    return hmac.new(settings.secret_key.encode(), b"echo sign-in state cookie", hashlib.sha256).hexdigest()


@lru_cache
def microsoft(settings: Settings) -> StarletteOAuth2App:
    oauth = OAuth()
    # The tenant's own metadata, so Authlib checks the token's issuer and signing keys against this tenant only.
    return oauth.register(
        "microsoft",
        client_id=settings.ms_client_id,
        client_secret=settings.ms_client_secret,
        server_metadata_url=f"{issuer(settings)}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
    )


def identity(settings: Settings, token: dict) -> tuple[str, str, str | None, str | None]:
    """The tenant id, object id, email and name from a verified sign-in, or AppError.

    Authlib only verifies the ID token when the stored sign-in state has a nonce, so a token without
    verified claims is refused here rather than trusted."""
    claims = token.get("userinfo")
    if not claims:
        raise AppError(400, "sign_in_failed", "Microsoft did not return a verified sign-in.")
    # Already checked by Authlib against the tenant metadata; checked again so a change there cannot let another tenant in.
    if claims.get("tid") != settings.ms_tenant_id or claims.get("iss") != issuer(settings):
        raise AppError(403, "wrong_tenant", "This account is not in the organization Echo is set up for.")
    if not claims.get("oid"):
        raise AppError(400, "sign_in_failed", "Microsoft did not return a verified sign-in.")
    return claims["tid"], claims["oid"], claims.get("email") or claims.get("preferred_username"), claims.get("name")
