from typing import Annotated

from fastapi import APIRouter, Depends

from apps.accounts.models.account import User
from apps.agents.routers.agent_router import OwnedAgent
from apps.preview.models.preview import NewPreview, PreviewUrl
from apps.preview.services import preview_service
from core.auth import current_user
from core.config import get_settings

router = APIRouter(prefix="/api/agents", dependencies=[Depends(current_user)])


@router.post("/{agent_id}/preview", summary="A link that shows a port of the agent's workspace in the browser", tags=["processes"])
async def preview(agent_id: OwnedAgent, body: NewPreview, user: Annotated[User, Depends(current_user)]) -> PreviewUrl:
    return PreviewUrl(url=preview_service.start_url(get_settings(), user.id, agent_id, body.port))
