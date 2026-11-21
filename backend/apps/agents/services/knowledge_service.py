"""What an agent has learned: its skills, which live in its workspace and are read through the
runner like every other workspace file, and its notes, which the harness's memory store keeps as one
Markdown file each in the api's data volume."""

import logging
from datetime import UTC, datetime
from pathlib import Path

from strands.vended_plugins.skills import Skill as HarnessSkill

from apps.agents.models.knowledge import Note, Skill, Skills
from apps.agents.services.paths import check_agent_id
from core.config import Settings
from core.errors import AppError
from sandbox.runner_sandbox import RunnerSandbox

logger = logging.getLogger(__name__)

SKILLS_DIR = ".agent/skills"
MAX_SKILLS = 100
MAX_SKILL_BYTES = 64 * 1024
# The agentskills.io limit; the harness puts the whole description in the system prompt.
MAX_DESCRIPTION = 1024
MAX_NOTES = 200

# Per skill folder: its name, 1 or 0 for whether it has a SKILL.md (any case, as the harness finds
# it), then the file's first 64 KB with NUL bytes removed so they cannot break the record.
_LIST_SKILLS = f"""cd {SKILLS_DIR} 2>/dev/null || exit 0
for d in */; do
  d=${{d%/}}; [ -d "$d" ] || continue
  f=$(find "$d" -maxdepth 1 -type f -iname skill.md | head -n 1)
  if [ -n "$f" ]; then printf '%s\\0%s\\0' "$d" 1; head -c {MAX_SKILL_BYTES} "$f" | tr -d '\\000'; else printf '%s\\0%s\\0' "$d" 0; fi
  printf '\\0'
done | head -z -n {(MAX_SKILLS + 1) * 3}"""


def check_skill(folder: str, content: str | None) -> tuple[str, str, str | None]:
    """(status, description, problem) for one skill folder, by the harness's own parser."""
    if content is None:
        return "skipped", "", "There is no SKILL.md in this folder."
    try:
        skill = HarnessSkill.from_content(content)
    except Exception as error:
        return "skipped", "", f"The harness cannot load it: {error}"
    try:
        HarnessSkill.from_content(content, strict=True)
    except ValueError:
        return "warning", skill.description, "The name should be 1 to 64 lowercase letters, digits and single hyphens."
    if skill.name != folder:
        return "warning", skill.description, f"The name in SKILL.md is {skill.name!r}, not the folder name {folder!r}."
    if len(skill.description) > MAX_DESCRIPTION:
        return "warning", skill.description, f"The description is longer than {MAX_DESCRIPTION} characters."
    return "ok", skill.description, None


async def list_skills(settings: Settings, agent_id: str) -> Skills:
    sandbox = RunnerSandbox(check_agent_id(agent_id), settings.runner_socket, settings.command_timeout)
    result = await sandbox.execute(_LIST_SKILLS)
    if result.exit_code != 0:
        logger.warning("Listing skills exited %s: %s", result.exit_code, result.stderr[-2000:])
        raise AppError(500, "command_failed", "The workspace could not list its skills.")
    fields = result.stdout.split("\0")
    records = [fields[i : i + 3] for i in range(0, len(fields) - 2, 3)]
    skills = []
    for folder, has_file, content in records[:MAX_SKILLS]:
        status, description, problem = check_skill(folder, content if has_file == "1" else None)
        skills.append(Skill(name=folder, description=description, path=f"{SKILLS_DIR}/{folder}/SKILL.md", status=status, problem=problem))
    return Skills(skills=skills, truncated=len(records) > MAX_SKILLS)


def _notes_dir(settings: Settings, agent_id: str) -> Path:
    return settings.data_dir / "memory" / check_agent_id(agent_id)


def _note_files(settings: Settings, agent_id: str) -> list[Path]:
    folder = _notes_dir(settings, agent_id)
    files = [p for p in folder.glob("*.md") if p.is_file() and not p.is_symlink()] if folder.is_dir() else []
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def list_notes(settings: Settings, agent_id: str) -> list[Note]:
    return [
        Note(name=p.stem, text=p.read_text(errors="replace"), updated_at=datetime.fromtimestamp(p.stat().st_mtime, UTC))
        for p in _note_files(settings, agent_id)[:MAX_NOTES]
    ]


def delete_note(settings: Settings, agent_id: str, name: str) -> None:
    # Matched against the files present, so nothing from the request is joined into a path.
    match = next((p for p in _note_files(settings, agent_id) if p.stem == name), None)
    if match is None:
        raise AppError(404, "note_not_found", "This agent has no note with this name.")
    match.unlink()


# shortcut: capped at 5000 files, so a skill folder past that (a vendored dependency) may miss a change; fine while skills are a few small files each.
_HASH_SKILLS = f"[ -d {SKILLS_DIR} ] || exit 0; find {SKILLS_DIR} -type f -print0 | head -z -n 5000 | xargs -0 -r sha1sum"


async def skill_hashes(settings: Settings, agent_id: str) -> dict[str, str]:
    """Path to checksum for every file under the skills folder, compared before and after a turn.
    Checksums, not git status, so a change the agent already committed still counts."""
    sandbox = RunnerSandbox(check_agent_id(agent_id), settings.runner_socket, settings.command_timeout)
    result = await sandbox.execute(_HASH_SKILLS)
    if result.exit_code != 0:
        raise OSError(f"Hashing skills exited {result.exit_code}")
    hashes = {}
    for line in result.stdout.splitlines():
        digest, _, path = line.partition("  ")
        if path:
            hashes[path] = digest
    return hashes


def changed_skills(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Skill folders with a file added, changed or removed."""
    changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
    return sorted({p.split("/")[2] for p in changed if p.count("/") >= 3})
