import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.chat.models.chat import ApprovalAnswer, Chat, ChatDetail, ChatList, StopResult, TurnRequest
from apps.agents.models.agent import DEFAULT_NAME
from apps.agents.services import titles
from apps.chat.services import agent_factory, approvals, chat_service, turn_service
from apps.chat.services.sse import message
from apps.credentials.models.credential import Deleted
from apps.credentials.services import credential_service, providers
from apps.agents.repositories import agents
from apps.agents.routers.agent_router import CurrentUser, Db, OwnedAgent
from apps.agents.services import knowledge_service
from apps.mcp.services import connect, mcp_service
from core.auth import current_user
from core.config import get_settings
from core.errors import AppError

# Every route needs a signed-in user, even one added later that forgets to ask for it.
router = APIRouter(dependencies=[Depends(current_user)])


@router.post("/api/agents/{agent_id}/chats", summary="Start a chat with an agent", tags=["chat"])
async def create_chat(agent_id: OwnedAgent) -> Chat:
    # Only an id: the chat is stored by its first turn, so chats nobody wrote in never pile up.
    return Chat(id=uuid.uuid4().hex)


@router.get("/api/agents/{agent_id}/chats", summary="List an agent's chats, most recently used first", tags=["chat"])
async def list_chats(agent_id: OwnedAgent, session: Db, before: str | None = None) -> ChatList:
    return await chat_service.list_chats(session, agent_id, before)


@router.get(
    "/api/agents/{agent_id}/chats/{chat_id}",
    summary="Open a chat with its latest turns",
    description="Turns come oldest first, the newest 30; pass `before` (a turn id) for the ones before it. "
    "Each turn's `events` are what its stream sent, so the chat is rebuilt the same way it was shown.",
    tags=["chat"],
)
async def get_chat(agent_id: OwnedAgent, chat_id: str, session: Db, before: str | None = None) -> ChatDetail:
    return await chat_service.chat_detail(session, agent_id, chat_id, before)


@router.delete("/api/agents/{agent_id}/chats/{chat_id}", summary="Delete a chat and everything the agent kept of it", tags=["chat"])
async def delete_chat(agent_id: OwnedAgent, chat_id: str, session: Db) -> Deleted:
    await chat_service.delete_chat(get_settings(), session, agent_id, chat_id)
    return Deleted(deleted=True)


@router.get(
    "/api/agents/{agent_id}/chats/{chat_id}/turns/{turn_id}/events",
    summary="Follow a turn as server-sent events",
    description="Sends `turn` and every event the turn has sent so far, then, while it runs, each new one until it ends. "
    "Closing this stream does not stop the turn.",
    tags=["chat"],
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def follow_turn(agent_id: OwnedAgent, chat_id: str, turn_id: str, session: Db) -> StreamingResponse:
    if turn := chat_service.live_turn(agent_id, chat_id, turn_id):
        return _stream(turn_service.subscribe(turn))
    stored = await chat_service.stored_turn(session, agent_id, chat_id, turn_id)

    async def replay():
        yield message("turn", {"id": turn_id}) + "".join(message(e["event"], e["data"]) for e in stored["events"])

    return _stream(replay())


@router.post(
    "/api/agents/{agent_id}/chats/{chat_id}/turns/{turn_id}/stop",
    summary="Stop a running turn",
    description="The turn's stream then ends with `stopped`. Stopping a turn that already ended does nothing.",
    tags=["chat"],
)
async def stop_turn(agent_id: OwnedAgent, chat_id: str, turn_id: str, session: Db) -> StopResult:
    if turn := chat_service.live_turn(agent_id, chat_id, turn_id):
        turn_service.stop(turn)
    else:
        # Already ended is fine; an unknown turn is not.
        await chat_service.stored_turn(session, agent_id, chat_id, turn_id)
        return StopResult(stopping=False)
    return StopResult(stopping=True)


@router.post(
    "/api/agents/{agent_id}/approvals/{approval_id}",
    summary="Answer a tool call that waits for your approval",
    description="`allow` runs the call, `deny` refuses it, and `always` runs it and every later call of the same tool in this chat. "
    "The turn's stream then sends `approval_done`. 404 `approval_not_found` when no call of yours waits under that id.",
    tags=["chat"],
)
async def answer_approval(agent_id: OwnedAgent, approval_id: str, body: ApprovalAnswer, user: CurrentUser) -> ApprovalAnswer:
    if not approvals.answer(approval_id, agent_id, user.id, body.decision):
        raise AppError(404, "approval_not_found", "Nothing is waiting for that approval. It may have been answered already or timed out.")
    return body


def _stream(events) -> StreamingResponse:
    # No buffering by a proxy, so events reach the browser as they happen.
    return StreamingResponse(events, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post(
    "/api/agents/{agent_id}/chats/{chat_id}/turns",
    summary="Send a message and stream the agent's turn as server-sent events",
    description="`credential_id` is one of your keys and `model` a model it can use. "
    "Streams `turn` ({id}) first, then `text` ({text}), `tool` ({id, name}) and then `done` ({stopReason, usage}), `error` ({code, message}) or `stopped`. "
    "The turn runs on the server until it ends: closing the stream does not stop it, and it can be followed again from its events route. "
    "The first turn of a workspace that was never named also sends `title` ({name}) once, at any point, possibly after `done`. "
    "Swagger UI cannot show a stream; use `curl -N`.",
    tags=["chat"],
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def send_turn(agent_id: OwnedAgent, chat_id: str, body: TurnRequest, user: CurrentUser, session: Db, request: Request) -> StreamingResponse:
    settings = get_settings()
    chat_service.check_id(chat_id)
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
    # Started by the turn, not here, so the stream begins at once and a slow server shows in it.
    servers = await mcp_service.turn_servers(settings, session, agent_id, user.id)
    side_tasks = []
    # A workspace started from a message alone: named from the message at once, so the list shows
    # something during the turn, then by the side model's title when it comes back.
    if agent.name == DEFAULT_NAME and agent.last_used_at is None:
        name = titles.provisional(body.prompt)
        await agents.update(session, agent_id, user.id, {"name": name})
        agent.name = name
        side_tasks.append(_title_task(request, agent_id, user.id, name, side_model, body.prompt))
        await session.commit()
    try:
        turn = turn_service.start_turn(
            request.app.state.chat_writer,
            agent_id,
            chat_id,
            lambda delegation, gate, mcp: agent_factory.build_agent(
                settings, agent_id, chat_id, model, f"{credential.provider}/{body.model}", side_model, agent.name, agent.job, needs_fixing,
                delegation=delegation, approvals=gate, mcp=mcp,
            ),
            body.prompt,
            settings.turn_timeout,
            title=_chat_title(body.prompt),
            model=f"{credential.provider}/{body.model}",
            effort=body.effort,
            snapshot=lambda: knowledge_service.skill_hashes(settings, agent_id),
            user_id=user.id,
            max_running=settings.max_running_turns,
            side_tasks=side_tasks,
            approval_mode=agent.approval_mode,
            mcp=connect.TurnMcp(servers, user.id, agent_id) if servers else None,
        )
    except turn_service.TurnRefused as refused:
        # Another request claimed the chat or the last slot while this one awaited the database.
        raise AppError(409 if refused.code == "chat_busy" else 429, refused.code, refused.text) from None
    # Queued with the turn's own writes, so a busy database never holds up the reply; the agents list shows which agent was used last.
    request.app.state.chat_writer.put(lambda db: agents.touch(db, agent_id))
    return _stream(turn_service.subscribe(turn))


def _chat_title(prompt: str) -> str:
    # The start of the first message, as a new workspace is first named; no model call.
    title = titles.provisional(prompt)
    return "New chat" if title == DEFAULT_NAME else title


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
