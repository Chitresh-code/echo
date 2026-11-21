from typing import Literal

from pydantic import BaseModel, Field

# Files the api reads or saves whole; past this the UI should not open them in an editor.
MAX_FILE_BYTES = 5 * 1024 * 1024


class Workspace(BaseModel):
    id: str


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


class WorkspaceFile(FileContent):
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
