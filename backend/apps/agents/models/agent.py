from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from core.db import UtcDateTime

# Files the api reads or saves whole in an agent's workspace; past this the UI does not open them in an editor.
MAX_FILE_BYTES = 5 * 1024 * 1024


class Agent(BaseModel):
    id: str
    name: str
    # The one task the user is teaching this agent, in their own words.
    job: str
    created_at: UtcDateTime
    last_used_at: UtcDateTime | None


# Plain text, shown as text: trimmed so a name of only spaces is refused.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Job = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class NewAgent(BaseModel):
    name: Name
    job: Job = ""


class AgentUpdate(BaseModel):
    name: Name | None = None
    job: Job | None = None


class TreeEntry(BaseModel):
    path: str
    type: Literal["file", "dir", "link", "other"]


class Tree(BaseModel):
    entries: list[TreeEntry]
    # True when the workspace has more entries than the tree returns.
    truncated: bool


class FileContent(BaseModel):
    content: str
    # "base64" when the file is not valid UTF-8 text.
    encoding: Literal["utf-8", "base64"]


class AgentFile(FileContent):
    path: str


class SaveFile(BaseModel):
    path: str
    content: str = Field(max_length=MAX_FILE_BYTES)


class GitFileStatus(BaseModel):
    path: str
    # git's porcelain status letters for the index and the working tree, such as "M", "A", "D", "?".
    index: str
    worktree: str
    original_path: str | None = None


class GitFileVersions(BaseModel):
    # null when the file is not in the last commit (new, or no commit yet), or no longer on disk.
    head: FileContent | None
    working: FileContent | None


class Usage(BaseModel):
    """Disk the agent's workspace and home take, and the most they may take."""

    used_bytes: int
    limit_bytes: int


class Process(BaseModel):
    """A long-running process in the agent's workspace, such as a dev server."""

    name: str
    command: str
    cwd: str | None
    status: Literal["running", "exited"]
    exit_code: int | None
    started_at: float = Field(description="Unix time it started")


class Processes(BaseModel):
    processes: list[Process]
    ports: list[int] = Field(description="TCP ports listening in the workspace, whichever process opened them")


class ProcessLog(BaseModel):
    name: str
    log: str = Field(description="The last lines of the process's output")
