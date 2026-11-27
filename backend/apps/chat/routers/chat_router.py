import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.chat.models.chat import Chat, TurnRequest
from apps.agents.models.agent import DEFAULT_NAME
from apps.agents.services import titles
from apps.chat.services import agent_factory, turn_service
from apps.chat.services.sse import message
from apps.credentials.services import credential_service, providers
from apps.agents.repositories import agents
from apps.agents.routers.agent_router import CurrentUser, Db, OwnedAgent
from apps.agents.services import knowledge_service
from apps.agents.services.paths import AGENT_ID
from core.auth import current_user
from core.config import get_settings
from core.errors import AppError

# Every route needs a signed-in user, even one added later that forgets to ask for it.
router = APIRouter(dependencies=[Depends(current_user)])


@router.post("/api/agents/{agent_id}/chats", summary="Start a chat with an agent", tags=["chat"])
async def create_chat(agent_id: OwnedAgent) -> Chat:
    # shortcut: chats are not stored, so there is no chat list or history and a reload shows no earlier messages; store chats, messages and usage in the database when sessions become resumable.
    return Chat(id=uuid.uuid4().hex)


@router.post(
    "/api/agents/{agent_id}/chats/{chat_id}/turns",
    summary="Send a message and stream the agent's turn as server-sent events",
    description="`credential_id` is one of your keys and `model` a model it can use. "
    "Streams `text` ({text}), `tool` ({id, name}) and then `done` ({stopReason, usage}) or `error` ({code, message}). "
    "The first turn of a workspace that was never named also sends `title` ({name}) once, at any point, possibly after `done`. "
    "Swagger UI cannot show a stream; use `curl -N`.",
    tags=["chat"],
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def send_turn(agent_id: OwnedAgent, chat_id: str, body: TurnRequest, user: CurrentUser, session: Db, request: Request) -> StreamingResponse:
    settings = get_settings()
    # Chat ids name a session folder, so they get the same check as agent ids.
    if not AGENT_ID.fullmatch(chat_id):
        raise AppError(400, "invalid_chat_id", "A chat id is 32 lowercase hex characters.")
    chat_key = f"{agent_id}/{chat_id}"
    if turn_service.is_busy(chat_key):
        raise AppError(409, "chat_busy", "This chat already has a turn in progress.")
    if not turn_service.can_start(user.id, settings.max_running_turns):
        raise AppError(429, "too_many_turns", turn_service.too_many_turns_message(settings.max_running_turns))
    # Looked up before the stream starts, so a missing or someone else's key is a plain 404. The
    # plain key lives only on this model's client, in this process; it never reaches the sandbox.
    credential, key = await credential_service.with_key(settings, session, user.id, body.credential_id)
    # shortcut: the model id goes to the provider unchecked, so a wrong one fails as turn_failed after the stream starts; the UI's picker will offer only listed models.
    model = providers.build_model(credential.provider, key, credential.base_url, body.model, body.effort)
    side_model = providers.build_side_model(credential.provider, key, credential.base_url, model)
    # Read per turn, so a rename, a new job or a broken skill reaches the very next message.
    agent = await agents.get(session, agent_id, user.id)
    needs_fixing = [s for s in (await knowledge_service.list_skills(settings, agent_id)).skills if s.status != "ok"]
    side_tasks = []
    # A workspace started from a message alone: named from the message at once, so the list shows
    # something during the turn, then by the side model's title when it comes back.
    if agent.name == DEFAULT_NAME and agent.last_used_at is None:
        name = titles.provisional(body.prompt)
        await agents.update(session, agent_id, user.id, {"name": name})
        agent.name = name
        side_tasks.append(_title_task(request, agent_id, user.id, name, side_model, body.prompt))
    # Recorded once the turn is accepted, so the agents list shows which agent was used last.
    await agents.touch(session, agent_id)
    await session.commit()
    stream = turn_service.stream_turn(
        chat_key,
        lambda delegation: agent_factory.build_agent(
            settings, agent_id, chat_id, model, f"{credential.provider}/{body.model}", side_model, agent.name, agent.job, needs_fixing, delegation=delegation
        ),
        body.prompt,
        settings.turn_timeout,
        lambda: knowledge_service.skill_hashes(settings, agent_id),
        user.id,
        settings.max_running_turns,
        side_tasks,
    )
    # No buffering by a proxy, so events reach the browser as they happen.
    return StreamingResponse(stream, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _title_task(request: Request, agent_id: str, user_id: str, provisional: str, side_model, prompt: str) -> turn_service.SideTask:
    async def work() -> str | None:
        title = await titles.generate(side_model, prompt)
        if title is None or title == provisional:
            return None
        # Its own session: the request's closes once the stream starts.
        async with async_sessionmaker(request.app.state.db_engine)() as session:
            renamed = await agents.rename_if(session, agent_id, user_id, provisional, title)
            await session.commit()
        return message("title", {"name": title}) if renamed else None

    return work
