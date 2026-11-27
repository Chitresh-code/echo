from pydantic import BaseModel, Field
from strands_harness.types.agent import Effort

from core.db import UtcDateTime


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


class ChatSummary(BaseModel):
    id: str
    title: str
    created_at: UtcDateTime
    updated_at: UtcDateTime
    # Whether a turn is running in it now.
    running: bool


class ChatList(BaseModel):
    chats: list[ChatSummary]
    # Whether older chats follow; ask again with `before` set to the last one's id.
    more: bool


class TurnEvent(BaseModel):
    event: str
    data: dict


class StoredTurn(BaseModel):
    id: str
    prompt: str
    # provider/model, or null for a turn imported from before chats were stored.
    model: str | None
    effort: str | None
    # running, done, failed, stopped or interrupted (the server restarted during it).
    status: str
    usage: dict | None
    # Whether the turn was too long to keep in full; its events stop early.
    truncated: bool
    started_at: UtcDateTime
    ended_at: UtcDateTime | None
    # The events the chat showed, as the turn's stream sent them.
    events: list[TurnEvent]


class ChatDetail(ChatSummary):
    turns: list[StoredTurn]
    # Whether earlier turns follow; ask again with `before` set to the first one's id.
    more: bool


class StopResult(BaseModel):
    # False when the turn had already ended, so there was nothing to stop.
    stopping: bool
