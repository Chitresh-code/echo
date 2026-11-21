"""Parses `git status --porcelain=v1 -z` output, kept apart from running git so it is tested with
fixed strings."""

from apps.agents.models.agent import GitFileStatus


def parse_porcelain(output: str) -> list[GitFileStatus]:
    # Each entry is "XY path" ending in NUL; a rename or copy is followed by its original path.
    fields = output.split("\0")
    entries = []
    i = 0
    while i < len(fields):
        field = fields[i]
        i += 1
        if len(field) < 4:
            continue
        index, worktree, path = field[0], field[1], field[3:]
        original = None
        if index in "RC" or worktree in "RC":
            original = fields[i]
            i += 1
        entries.append(GitFileStatus(path=path, index=index, worktree=worktree, original_path=original))
    return entries
