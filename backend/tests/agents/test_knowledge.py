import os

import pytest

from apps.agents.services.knowledge_service import check_skill
from core.config import get_settings
from tests.helpers.accounts import own

WS = "0123456789abcdef" * 2
OK = "---\nname: weekly-report\ndescription: Use for the weekly payout report.\n---\n# Steps\n1. Run it.\n"


@pytest.fixture(autouse=True)
def _owns_ws(client, user):
    own(client, user, WS)


def skills_output(*records):
    """The runner's answer to the skills listing: folder, has-file flag and content per skill."""
    data = "".join(f"{folder}\0{'0' if content is None else '1'}\0{content or ''}\0" for folder, content in records)
    return [{"stream": "stdout", "data": data}, {"exit_code": 0, "timed_out": False}]


@pytest.mark.parametrize(
    ("folder", "content", "status", "problem"),
    [
        ("weekly-report", OK, "ok", None),
        ("weekly-report", None, "skipped", "no SKILL.md"),
        ("weekly-report", "# Steps only, no front matter\n", "skipped", "cannot load"),
        ("weekly-report", "---\nname: weekly-report\n---\nbody\n", "skipped", "description"),
        ("weekly-report", "---\nname: [unclosed\ndescription: x\n---\n", "skipped", "cannot load"),
        ("other-folder", OK, "warning", "not the folder name"),
        ("Weekly_Report", OK.replace("weekly-report", "Weekly_Report"), "warning", "lowercase"),
        ("weekly-report", OK.replace("Use for the weekly payout report.", "x" * 1025), "warning", "longer than 1024"),
    ],
)
def test_check_skill(folder, content, status, problem):
    got_status, _, got_problem = check_skill(folder, content)
    assert got_status == status
    assert (got_problem is None) if problem is None else (problem in got_problem)


def test_list_skills(client, fake_runner):
    fake_runner.lines = skills_output(("weekly-report", OK), ("half-done", None))
    data = client.get(f"/api/agents/{WS}/skills").json()["data"]
    assert data["truncated"] is False
    assert data["skills"][0] == {
        "name": "weekly-report", "description": "Use for the weekly payout report.",
        "path": ".agent/skills/weekly-report/SKILL.md", "status": "ok", "problem": None,
    }
    assert data["skills"][1]["status"] == "skipped"
    assert ".agent/skills" in fake_runner.requests[0]["command"]


def test_list_skills_is_capped(client, fake_runner, monkeypatch):
    monkeypatch.setattr("apps.agents.services.knowledge_service.MAX_SKILLS", 1)
    fake_runner.lines = skills_output(("a", OK), ("b", OK))
    data = client.get(f"/api/agents/{WS}/skills").json()["data"]
    assert len(data["skills"]) == 1 and data["truncated"] is True


def test_no_skills_folder_is_an_empty_list(client, fake_runner):
    fake_runner.lines = [{"exit_code": 0, "timed_out": False}]
    assert client.get(f"/api/agents/{WS}/skills").json()["data"] == {"skills": [], "truncated": False}


def notes_dir():
    folder = get_settings().data_dir / "memory" / WS
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def test_notes_newest_first_and_delete(client):
    folder = notes_dir()
    (folder / "older.md").write_text("Payouts land up to 2 days late.")
    (folder / "newer.md").write_text("Totals go last.")
    os.utime(folder / "older.md", (1, 1))
    (folder / "not-a-note.txt").write_text("ignored")
    notes = client.get(f"/api/agents/{WS}/notes").json()["data"]
    assert [n["name"] for n in notes] == ["newer", "older"] and notes[1]["text"] == "Payouts land up to 2 days late."
    assert notes[1]["updated_at"] == "1970-01-01T00:00:01Z"
    assert client.delete(f"/api/agents/{WS}/notes/older").json()["data"] == {"deleted": True}
    assert not (folder / "older.md").exists() and (folder / "newer.md").exists()


def test_deleting_an_unknown_or_outside_note_is_404(client):
    folder = notes_dir()
    (folder.parent / "secret.md").write_text("not this agent's")
    for name in ["missing", "..%2Fsecret", "../secret"]:
        r = client.delete(f"/api/agents/{WS}/notes/{name}")
        assert r.status_code == 404
    assert (folder.parent / "secret.md").exists()


def test_an_agent_with_no_notes_has_an_empty_list(client):
    assert client.get(f"/api/agents/{WS}/notes").json()["data"] == []


@pytest.mark.parametrize("request_", [("get", "skills"), ("get", "notes"), ("delete", "notes/x")])
def test_someone_elses_agent_is_404(client, fake_runner, request_):
    method, path = request_
    r = getattr(client, method)(f"/api/agents/{'d' * 32}/{path}")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "agent_not_found") and fake_runner.requests == []
