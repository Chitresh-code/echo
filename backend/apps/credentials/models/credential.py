from typing import Annotated, Literal

from pydantic import BaseModel, Field, SecretStr, StringConstraints

from core.db import UtcDateTime

Provider = Literal["anthropic", "openai", "google", "openai_compatible"]
ModelId = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^\S+$")]


class NewCredential(BaseModel):
    provider: Provider
    label: str = Field(min_length=1, max_length=100, description="A name to tell your keys apart, such as Work Anthropic")
    # SecretStr keeps the key out of reprs and logs.
    api_key: SecretStr = Field(min_length=1, max_length=1000)
    base_url: str | None = Field(None, max_length=500, description="Only for openai_compatible: an https address such as https://api.example.com/v1")
    models: list[ModelId] | None = Field(
        None, min_length=1, max_length=50,
        description="Only for openai_compatible: the model ids to offer, for an endpoint with no model list. The key is then checked with a one-token chat request to the first.",
    )


class Credential(BaseModel):
    """A stored key as the API shows it: never the key itself, only its last four characters."""

    id: str
    provider: Provider
    label: str
    base_url: str | None
    key_hint: str
    # The model ids the user gave, or null when the provider lists its own.
    models: list[str] | None = None
    created_at: UtcDateTime


class ProviderModel(BaseModel):
    id: str
    name: str


class Deleted(BaseModel):
    deleted: bool
