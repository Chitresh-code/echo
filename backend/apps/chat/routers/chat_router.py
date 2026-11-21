import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from apps.chat.models.chat import Chat, Models, TurnRequest
from apps.chat.services import agent_factory, turn_service
from apps.workspaces.services.paths import WORKSPACE_ID, check_workspace_id
from apps.workspaces.services.workspace_service import require_workspace
from core.config import get_settings
from core.errors import AppError

router = APIRouter()


@router.get("/api/models", summary="The models a turn may use, and the default", tags=["chat"])
def list_models() -> Models:
    settings = get_settings()
    return Models(models=list(settings.models), default=settings.default_model)


@router.post("/api/workspaces/{workspace_id}/chats", summary="Start a chat in a workspace", tags=["chat"])
async def create_chat(workspace_id: str) -> Chat:
    await require_workspace(get_settings(), workspace_id)
    # shortcut: chats are not stored, so there is no chat list or history; add them with the browser UI.
    return Chat(id=uuid.uuid4().hex)


@router.post(
    "/api/workspaces/{workspace_id}/chats/{chat_id}/turns",
    summary="Send a message and stream the agent's turn as server-sent events",
    description="Streams `text` ({text}), `tool` ({id, name}) and then `done` ({stopReason}) or `error` ({code, message}). "
    "Swagger UI cannot show a stream; use `curl -N`.",
    tags=["chat"],
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def send_turn(workspace_id: str, chat_id: str, body: TurnRequest) -> StreamingResponse:
    settings = get_settings()
    check_workspace_id(workspace_id)
    # Chat ids name a session folder, so they get the same check as workspace ids.
    if not WORKSPACE_ID.fullmatch(chat_id):
        raise AppError(400, "invalid_chat_id", "A chat id is 32 lowercase hex characters.")
    model = agent_factory.check_model(settings, body.model)
    await require_workspace(settings, workspace_id)
    chat_key = f"{workspace_id}/{chat_id}"
    if turn_service.is_busy(chat_key):
        raise AppError(409, "chat_busy", "This chat already has a turn in progress.")
    stream = turn_service.stream_turn(
        chat_key,
        lambda: agent_factory.build_agent(settings, workspace_id, chat_id, model),
        body.prompt,
        settings.turn_timeout,
    )
    # No buffering by a proxy, so events reach the browser as they happen.
    return StreamingResponse(stream, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
