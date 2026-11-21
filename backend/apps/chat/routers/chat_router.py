import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from apps.chat.models.chat import Chat, TurnRequest
from apps.chat.services import agent_factory, turn_service
from apps.credentials.services import credential_service, providers
from apps.workspaces.routers.workspace_router import CurrentUser, Db, OwnedWorkspace
from apps.workspaces.services.paths import WORKSPACE_ID
from core.auth import current_user
from core.config import get_settings
from core.errors import AppError

# Every route needs a signed-in user, even one added later that forgets to ask for it.
router = APIRouter(dependencies=[Depends(current_user)])


@router.post("/api/workspaces/{workspace_id}/chats", summary="Start a chat in a workspace", tags=["chat"])
async def create_chat(workspace_id: OwnedWorkspace) -> Chat:
    # shortcut: chats are not stored, so there is no chat list or history; add them with the browser UI.
    return Chat(id=uuid.uuid4().hex)


@router.post(
    "/api/workspaces/{workspace_id}/chats/{chat_id}/turns",
    summary="Send a message and stream the agent's turn as server-sent events",
    description="`credential_id` is one of your keys and `model` a model it can use. "
    "Streams `text` ({text}), `tool` ({id, name}) and then `done` ({stopReason}) or `error` ({code, message}). "
    "Swagger UI cannot show a stream; use `curl -N`.",
    tags=["chat"],
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def send_turn(workspace_id: OwnedWorkspace, chat_id: str, body: TurnRequest, user: CurrentUser, session: Db) -> StreamingResponse:
    settings = get_settings()
    # Chat ids name a session folder, so they get the same check as workspace ids.
    if not WORKSPACE_ID.fullmatch(chat_id):
        raise AppError(400, "invalid_chat_id", "A chat id is 32 lowercase hex characters.")
    chat_key = f"{workspace_id}/{chat_id}"
    if turn_service.is_busy(chat_key):
        raise AppError(409, "chat_busy", "This chat already has a turn in progress.")
    # Looked up before the stream starts, so a missing or someone else's key is a plain 404. The
    # plain key lives only on this model's client, in this process; it never reaches the sandbox.
    credential, key = await credential_service.with_key(settings, session, user.id, body.credential_id)
    # shortcut: the model id goes to the provider unchecked, so a wrong one fails as turn_failed after the stream starts; the UI's picker will offer only listed models.
    # shortcut: a chat may switch provider between turns, which is untested with provider-specific history such as reasoning blocks; check it with the Agent model work.
    model = providers.build_model(credential.provider, key, credential.base_url, body.model)
    stream = turn_service.stream_turn(
        chat_key,
        lambda: agent_factory.build_agent(settings, workspace_id, chat_id, model),
        body.prompt,
        settings.turn_timeout,
    )
    # No buffering by a proxy, so events reach the browser as they happen.
    return StreamingResponse(stream, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
