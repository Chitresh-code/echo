from typing import Literal

from pydantic import BaseModel

from core.db import UtcDateTime


class Skill(BaseModel):
    # The skill's folder under .agent/skills/.
    name: str
    description: str
    # Relative to the workspace, so the file routes open it.
    path: str
    # skipped: the harness does not load it. warning: it loads but breaks the SKILL.md format.
    status: Literal["ok", "warning", "skipped"]
    problem: str | None


class Skills(BaseModel):
    skills: list[Skill]
    # True when the workspace has more skills than the list returns.
    truncated: bool


class Note(BaseModel):
    # The note's file name without .md, which names it for delete.
    name: str
    text: str
    updated_at: UtcDateTime
