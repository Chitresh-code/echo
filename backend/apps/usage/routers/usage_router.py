from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.accounts.models.account import User
from apps.usage.models.usage import UsageReport
from apps.usage.services import usage_service
from core.auth import current_user
from core.db import db

router = APIRouter(prefix="/api/usage", tags=["usage"], dependencies=[Depends(current_user)])
CurrentUser = Annotated[User, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(db)]


@router.get(
    "",
    summary="Your token use and estimated cost over a range of dates",
    description="`start` and `end` are inclusive dates read in the time zone `tz` (an IANA name such as Europe/London), "
    f"at most {usage_service.MAX_DAYS} days apart. Costs are in millionths of a US dollar and are estimates from list prices. "
    "Usage is counted per model call, including subagents and the side work of a turn, and is kept after a workspace or key is deleted.",
)
async def get_usage(
    user: CurrentUser, session: Db, start: date, end: date, tz: Annotated[str, Query(max_length=64)] = "UTC",
) -> UsageReport:
    return await usage_service.report(session, user.id, start, end, tz)
