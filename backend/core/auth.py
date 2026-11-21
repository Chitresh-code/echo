"""Who is making the request. Routes that need a signed-in user depend on `current_user`, and every
request passes `check_origin`."""

from urllib.parse import urlsplit

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.accounts.models.account import User
from apps.accounts.services import session_service
from core.config import get_settings
from core.db import db
from core.errors import AppError


async def current_user(request: Request, session: AsyncSession = Depends(db)) -> User:
    user = await session_service.user_for(session, request.cookies.get(session_service.COOKIE))
    if user is None:
        raise AppError(401, "not_signed_in", "Sign in at /api/auth/login first.")
    return user


_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def check_origin(request: Request) -> None:
    """Refuse a state-changing request sent by another site's page with the user's cookie. SameSite=Lax
    already holds the cookie back from cross-site posts; this also covers same-site neighbours and
    old browsers."""
    if request.method not in _UNSAFE:
        return
    source = request.headers.get("origin") or request.headers.get("referer")
    # Browsers send Origin on every POST, PUT, PATCH and DELETE, so a request with neither header
    # comes from a client like curl, which holds its own cookie and cannot be tricked into sending it.
    if source is None:
        return
    parts = urlsplit(source)
    if f"{parts.scheme}://{parts.netloc}".lower() != get_settings().public_url.lower():
        raise AppError(403, "bad_origin", "This request came from another site. Open Echo at its own address.")
