from pydantic import BaseModel, Field
from strands_harness.types.agent import Effort


class Chat(BaseModel):
    id: str


class TurnRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)
    # One of your keys from GET /api/credentials.
    credential_id: str = Field(min_length=1, max_length=64)
    # A model id the key can use, as GET /api/credentials/{id}/models lists it.
    model: str = Field(min_length=1, max_length=200, pattern=r"^\S+$")
    # How hard the model reasons. `auto` is the harness's recommended level for the model; the
    # levels a model takes differ, and an unsupported one is refused before the turn starts.
    effort: Effort = "auto"
