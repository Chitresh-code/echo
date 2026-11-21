"""Sign-in sessions. The cookie holds a random token; the database holds only its SHA-256, so a
copy of the database cannot be used to sign in as anyone."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from apps.accounts.models.account import User
from apps.accounts.repositories import sessions

COOKIE = "echo_session"
# shortcut: a session lasts its full 7 days even after the user is removed in Entra; add revocation (an admin view, or a shorter session refreshed against Entra) when more than one team uses Echo.
LIFETIME = timedelta(days=7)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create(db: AsyncSession, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    await sessions.add(db, _hash(token), user_id, now, now + LIFETIME)
    await db.commit()
    return token


async def user_for(db: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None
    return await sessions.user_for(db, _hash(token), datetime.now(UTC))


async def end(db: AsyncSession, token: str | None) -> None:
    if token:
        await sessions.delete(db, _hash(token))
        await db.commit()
