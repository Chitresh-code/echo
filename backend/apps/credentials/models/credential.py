from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

Provider = Literal["anthropic", "openai", "google", "openai_compatible"]


class NewCredential(BaseModel):
    provider: Provider
    label: str = Field(min_length=1, max_length=100, description="A name to tell your keys apart, such as Work Anthropic")
    # SecretStr keeps the key out of reprs and logs.
    api_key: SecretStr = Field(min_length=1, max_length=1000)
    base_url: str | None = Field(None, max_length=500, description="Only for openai_compatible: an https address such as https://api.example.com/v1")


class Credential(BaseModel):
    """A stored key as the API shows it: never the key itself, only its last four characters."""

    id: str
    provider: Provider
    label: str
    base_url: str | None
    key_hint: str
    created_at: datetime


class ProviderModel(BaseModel):
    id: str
    name: str


class Deleted(BaseModel):
    deleted: bool
