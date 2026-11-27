"""Sign a test client in without Microsoft, by writing the user and session straight to the app's
database. The sign-in flow itself is tested in tests/accounts."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from apps.accounts.repositories import users
from apps.accounts.services import session_service
from apps.agents.repositories import agents


def _run(client, work):
    async def go():
        async with AsyncSession(client.app.state.db_engine) as db:
            result = await work(db)
            await db.commit()
            return result

    return client.portal.call(go)


def sign_in_as(client, name: str = "ada") -> str:
    """Sign `client` in as a new user and return the user's id. The client must be started."""

    async def work(db):
        user = await users.sign_in(db, "11111111-1111-1111-1111-111111111111", str(uuid.uuid4()), f"{name}@example.com", name)
        token = await session_service.create(db, user.id)
        return user.id, token

    user_id, token = _run(client, work)
    client.cookies.set(session_service.COOKIE, token)
    return user_id


def own(client, user_id: str, agent_id: str) -> None:
    """Record `user_id` as the owner of an agent, as creating it through the API would. A test
    that restarts the app signs in again, so an earlier owner is replaced."""

    async def work(db):
        await db.execute(agents.agents.delete().where(agents.agents.c.id == agent_id))
        # Named, as a workspace that was never named gets titled on its first turn.
        await agents.add(db, agent_id, user_id, "Test agent")

    _run(client, work)


def add_key(client, user_id: str, key: str = "sk-ant-test-key-for-turns-0000", provider: str = "anthropic") -> str:
    """Store a provider key for `user_id` without the provider check, and return its id."""
    from apps.credentials.repositories import credentials
    from apps.credentials.services import crypto
    from core.config import get_settings

    async def work(db):
        return await credentials.add(db, user_id, provider, "Test", None, "", crypto.encrypt(get_settings(), key))

    return _run(client, work).id
