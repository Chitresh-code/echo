from sqlalchemy.ext.asyncio import AsyncSession

from apps.credentials.models.credential import Credential, NewCredential, ProviderModel
from apps.credentials.repositories import credentials
from apps.credentials.services import crypto, providers, safe_http
from core.config import Settings
from core.errors import AppError


def _not_found() -> AppError:
    # Someone else's key answers exactly like a missing one, so ids cannot be probed.
    return AppError(404, "credential_not_found", "There is no key with this id.")


async def add(settings: Settings, db: AsyncSession, owner_id: str, new: NewCredential) -> Credential:
    key = new.api_key.get_secret_value().strip()
    if new.provider == "openai_compatible":
        base_url = safe_http.check_base_url(new.base_url)
    elif new.base_url is not None:
        raise AppError(400, "invalid_base_url", "Only openai_compatible keys take a base_url.")
    else:
        base_url = None
    # Listing models proves the key works before it is stored.
    await providers.list_models(new.provider, key, base_url)
    # A short key would give away too much of itself in four characters.
    hint = key[-4:] if len(key) >= 16 else ""
    credential = await credentials.add(db, owner_id, new.provider, new.label, base_url, hint, crypto.encrypt(settings, key))
    await db.commit()
    return credential


async def list_credentials(db: AsyncSession, owner_id: str) -> list[Credential]:
    return await credentials.list_for(db, owner_id)


async def with_key(settings: Settings, db: AsyncSession, owner_id: str, credential_id: str) -> tuple[Credential, str]:
    """The user's credential and its plain key, for calling the provider. The key never goes further."""
    found = await credentials.get(db, credential_id, owner_id)
    if found is None:
        raise _not_found()
    credential, token = found
    return credential, crypto.decrypt(settings, token)


async def list_models(settings: Settings, db: AsyncSession, owner_id: str, credential_id: str) -> list[ProviderModel]:
    credential, key = await with_key(settings, db, owner_id, credential_id)
    return await providers.list_models(credential.provider, key, credential.base_url)


async def delete(db: AsyncSession, owner_id: str, credential_id: str) -> None:
    if not await credentials.delete(db, credential_id, owner_id):
        raise _not_found()
    await db.commit()
