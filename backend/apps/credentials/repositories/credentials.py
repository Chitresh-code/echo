"""Stored provider keys. Every read takes the owner, so a key lookup that ignores the owner cannot be
written by mistake."""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from apps.credentials.models.credential import Credential
from core.db import metadata

credentials = sa.Table(
    "credentials", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("owner_id", sa.String),
    sa.Column("provider", sa.String),
    sa.Column("label", sa.String),
    sa.Column("base_url", sa.String),
    sa.Column("key_hint", sa.String),
    sa.Column("models", sa.JSON),
    sa.Column("key_encrypted", sa.LargeBinary),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)
_SHOWN = [credentials.c[name] for name in Credential.model_fields]


async def add(
    db: AsyncSession, owner_id: str, provider: str, label: str, base_url: str | None, key_hint: str, key_encrypted: bytes,
    models: list[str] | None = None,
) -> Credential:
    row = {
        "id": uuid.uuid4().hex, "provider": provider, "label": label, "base_url": base_url,
        "key_hint": key_hint, "models": models, "created_at": datetime.now(UTC),
    }
    await db.execute(credentials.insert().values(owner_id=owner_id, key_encrypted=key_encrypted, **row))
    return Credential(**row)


async def list_for(db: AsyncSession, owner_id: str) -> list[Credential]:
    query = sa.select(*_SHOWN).where(credentials.c.owner_id == owner_id).order_by(credentials.c.created_at.desc())
    return [Credential(**row._mapping) for row in await db.execute(query)]


async def get(db: AsyncSession, credential_id: str, owner_id: str) -> tuple[Credential, bytes] | None:
    """The credential and its encrypted key, or None when it is missing or someone else's."""
    query = sa.select(*_SHOWN, credentials.c.key_encrypted).where(credentials.c.id == credential_id, credentials.c.owner_id == owner_id)
    row = (await db.execute(query)).first()
    if row is None:
        return None
    fields = dict(row._mapping)
    return Credential(**{k: fields[k] for k in Credential.model_fields}), fields["key_encrypted"]


async def delete(db: AsyncSession, credential_id: str, owner_id: str) -> bool:
    result = await db.execute(credentials.delete().where(credentials.c.id == credential_id, credentials.c.owner_id == owner_id))
    return result.rowcount > 0
