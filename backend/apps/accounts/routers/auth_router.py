import logging

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.accounts.models.account import SignedOut, User
from apps.accounts.repositories import users
from apps.accounts.services import oidc, session_service
from core.auth import current_user
from core.config import get_settings
from core.db import db
from core.errors import AppError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# Until there is a UI, signing in lands on the API reference, where the session cookie is used.
AFTER_SIGN_IN = "/api/docs"
SIGN_IN_FAILED = "/docs/signing-in.html"


@router.get("/login", summary="Sign in with Microsoft", response_class=RedirectResponse, status_code=302)
async def login(request: Request):
    settings = get_settings()
    # select_account lets someone signed in to Microsoft with several accounts pick the work one.
    return await oidc.microsoft(settings).authorize_redirect(request, f"{settings.public_url}/api/auth/callback", prompt="select_account")


@router.get("/callback", summary="Where Microsoft returns after sign-in", response_class=RedirectResponse, status_code=302)
async def callback(request: Request, session: AsyncSession = Depends(db)):
    settings = get_settings()
    try:
        token = await oidc.microsoft(settings).authorize_access_token(request)
        tenant_id, object_id, email, name = oidc.identity(settings, token)
    except AppError as exc:
        logger.warning("Sign-in refused: %s", exc.code)
        return RedirectResponse(f"{SIGN_IN_FAILED}?error={exc.code}", status_code=302)
    except Exception:
        # The provider's own error text stays in the log; the browser only gets a code.
        logger.exception("Sign-in failed")
        return RedirectResponse(f"{SIGN_IN_FAILED}?error=sign_in_failed", status_code=302)

    user = await users.sign_in(session, tenant_id, object_id, email, name)
    # Any session the browser already had is ended, so a sign-in always starts a fresh token.
    await session_service.end(session, request.cookies.get(session_service.COOKIE))
    token = await session_service.create(session, user.id)
    response = RedirectResponse(AFTER_SIGN_IN, status_code=302)
    response.set_cookie(
        session_service.COOKIE, token,
        max_age=int(session_service.LIFETIME.total_seconds()),
        httponly=True, samesite="lax", secure=settings.public_url.startswith("https://"), path="/",
    )
    return response


@router.post("/logout", summary="Sign out and end this session")
async def logout(request: Request, response: Response, session: AsyncSession = Depends(db)) -> SignedOut:
    await session_service.end(session, request.cookies.get(session_service.COOKIE))
    response.delete_cookie(session_service.COOKIE, path="/", httponly=True, samesite="lax", secure=get_settings().public_url.startswith("https://"))
    return SignedOut(signed_out=True)


@router.get("/me", summary="The signed-in user")
async def me(user: User = Depends(current_user)) -> User:
    return user
