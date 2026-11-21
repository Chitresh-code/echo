from pydantic import BaseModel, Field


class Chat(BaseModel):
    id: str


class Models(BaseModel):
    models: list[str]
    default: str


class TurnRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)
    # One of the models from GET /api/models; the default when left out.
    model: str | None = None
