from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.accounts.models.account import User
from apps.credentials.models.credential import Credential, Deleted, NewCredential, ProviderModel
from apps.credentials.services import credential_service as service
from core.auth import current_user
from core.config import get_settings
from core.db import db

# Every route needs a signed-in user, even one added later that forgets to ask for it.
router = APIRouter(prefix="/api/credentials", tags=["keys"], dependencies=[Depends(current_user)])
CurrentUser = Annotated[User, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(db)]


@router.post(
    "",
    summary="Add a model provider key",
    description="The key is checked by listing the provider's models, then stored encrypted. It is never shown again; "
    "responses carry only its last four characters. `base_url` is required for `openai_compatible` and refused otherwise.",
)
async def add_credential(body: NewCredential, user: CurrentUser, session: Db) -> Credential:
    return await service.add(get_settings(), session, user.id, body)


@router.get("", summary="List your keys, newest first")
async def list_credentials(user: CurrentUser, session: Db) -> list[Credential]:
    return await service.list_credentials(session, user.id)


@router.delete("/{credential_id}", summary="Delete a key")
async def delete_credential(credential_id: str, user: CurrentUser, session: Db) -> Deleted:
    await service.delete(session, user.id, credential_id)
    return Deleted(deleted=True)


@router.get("/{credential_id}/models", summary="The models this key can use")
async def list_models(credential_id: str, user: CurrentUser, session: Db) -> list[ProviderModel]:
    return await service.list_models(get_settings(), session, user.id, credential_id)
