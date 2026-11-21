from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.accounts.models.account import User
from apps.agents.models.agent import Agent, AgentFile, AgentUpdate, GitFileStatus, GitFileVersions, NewAgent, SaveFile, Tree, Usage
from apps.agents.models.knowledge import Note, Skills
from apps.credentials.models.credential import Deleted
from apps.agents.services import agent_service as service
from apps.agents.services import knowledge_service
from core.auth import current_user
from core.config import get_settings
from core.db import db

# Every route needs a signed-in user, even one added later that forgets to ask for it.
router = APIRouter(prefix="/api/agents", dependencies=[Depends(current_user)])
PathQuery = Query(description="Path relative to the agent's workspace root, such as src/app.py")
CurrentUser = Annotated[User, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(db)]


async def owned_agent(agent_id: str, user: CurrentUser, session: Db) -> str:
    """The path's agent id, once it is known to belong to the signed-in user."""
    return await service.require_agent(session, user.id, agent_id)


OwnedAgent = Annotated[str, Depends(owned_agent)]


@router.post("", summary="Create an agent with a name and the job it learns", tags=["agents"])
async def create_agent(body: NewAgent, user: CurrentUser, session: Db) -> Agent:
    return await service.create_agent(get_settings(), session, user.id, body)


@router.get("", summary="List agents, most recently used first", tags=["agents"])
async def list_agents(user: CurrentUser, session: Db) -> list[Agent]:
    return await service.list_agents(session, user.id)


@router.get("/{agent_id}", summary="One agent's name, job and when it was last used", tags=["agents"])
async def get_agent(agent_id: OwnedAgent, user: CurrentUser, session: Db) -> Agent:
    return await service.get_agent(session, user.id, agent_id)


@router.patch("/{agent_id}", summary="Rename an agent or change its job", tags=["agents"])
async def update_agent(agent_id: OwnedAgent, body: AgentUpdate, user: CurrentUser, session: Db) -> Agent:
    return await service.update_agent(session, user.id, agent_id, body)


@router.delete("/{agent_id}", summary="Delete an agent with its files, skills, notes and chats, for good", tags=["agents"])
async def delete_agent(agent_id: OwnedAgent, user: CurrentUser, session: Db) -> Deleted:
    await service.delete_agent(get_settings(), session, user.id, agent_id)
    return Deleted(deleted=True)


@router.get("/{agent_id}/usage", summary="Disk the agent's files take, and its limit", tags=["agents"])
async def usage(agent_id: OwnedAgent) -> Usage:
    return await service.usage(get_settings(), agent_id)


@router.get("/{agent_id}/tree", summary="List the files in an agent's workspace, without .git", tags=["agents"])
async def tree(agent_id: OwnedAgent) -> Tree:
    return await service.tree(get_settings(), agent_id)


@router.get("/{agent_id}/file", summary="Read a file", tags=["agents"])
async def read_file(agent_id: OwnedAgent, path: str = PathQuery) -> AgentFile:
    content = await service.read_file(get_settings(), agent_id, path)
    return AgentFile(path=path, **content.model_dump())


@router.put("/{agent_id}/file", summary="Save a text file, creating its folders", tags=["agents"])
async def write_file(agent_id: OwnedAgent, body: SaveFile) -> AgentFile:
    await service.write_file(get_settings(), agent_id, body.path, body.content)
    return AgentFile(path=body.path, content=body.content, encoding="utf-8")


@router.get("/{agent_id}/git/status", summary="Changed files since the last commit", tags=["git"])
async def git_status(agent_id: OwnedAgent) -> list[GitFileStatus]:
    return await service.git_status(get_settings(), agent_id)


@router.get("/{agent_id}/git/file", summary="A file's last committed and current versions, for a diff", tags=["git"])
async def git_file_versions(agent_id: OwnedAgent, path: str = PathQuery) -> GitFileVersions:
    return await service.git_file_versions(get_settings(), agent_id, path)


@router.get("/{agent_id}/skills", summary="The agent's skills, and any the harness would skip or warns about", tags=["knowledge"])
async def list_skills(agent_id: OwnedAgent) -> Skills:
    return await knowledge_service.list_skills(get_settings(), agent_id)


@router.get("/{agent_id}/notes", summary="What the agent remembers across chats, newest first", tags=["knowledge"])
async def list_notes(agent_id: OwnedAgent) -> list[Note]:
    return knowledge_service.list_notes(get_settings(), agent_id)


@router.delete("/{agent_id}/notes/{name}", summary="Make the agent forget one note", tags=["knowledge"])
async def delete_note(agent_id: OwnedAgent, name: str) -> Deleted:
    knowledge_service.delete_note(get_settings(), agent_id, name)
    return Deleted(deleted=True)
