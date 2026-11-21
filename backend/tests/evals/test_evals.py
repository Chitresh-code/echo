import io

from evals import run as runner
from evals.tasks import PLANTED, TASKS


def test_events_are_parsed_from_the_stream():
    lines = ["event: text", 'data: {"text": "hi"}', "", "event: done", 'data: {"stopReason": "end_turn", "usage": {"inputTokens": 5}}', ""]
    assert runner.parse_events(lines) == [("text", {"text": "hi"}), ("done", {"stopReason": "end_turn", "usage": {"inputTokens": 5}})]


def test_run_stops_at_the_token_cap(monkeypatch):
    ran = []

    def fake(client, task, *args):
        ran.append(task.name)
        return {"task": task.name, "tools": 1, "tokens": 300, "error": None, "seconds": 1}

    monkeypatch.setattr(runner, "run_task", fake)
    out = io.StringIO()
    assert runner.run(None, TASKS, "c", "m", "low", max_tokens=500, out=out) == 600
    assert ran == [t.name for t in TASKS[:2]]
    assert out.getvalue().count("SKIP") == len(TASKS) - 2


def test_planted_check_fails_when_the_agent_obeyed_the_file():
    files = dict(PLANTED, **{"SUMMARY.md": "An inventory tracker."})
    planted = next(t for t in TASKS if t.name == "planted")
    assert planted.check(files.get, set(), []) is None
    assert "deleted" in planted.check({"SUMMARY.md": "x"}.get, set(), [])


def test_learns_check_needs_the_corrections_and_a_skill():
    learns = next(t for t in TASKS if t.name == "learns")
    good = "- 2026-11-10 Acme 120.50\n- 2026-11-11 Globex 80.00\n\nTotal: 200.50\n"
    assert learns.check({"report-week2.md": good}.get, set(), ["payout-report"]) is None
    assert "no skill" in learns.check({"report-week2.md": good}.get, set(), [])
    assert "YYYY-MM-DD" in learns.check({"report-week2.md": good.replace("2026-11-10", "11/10/2026")}.get, set(), ["s"])
    assert "last line" in learns.check({"report-week2.md": "Total: 200.50\n- 2026-11-10 Acme\n"}.get, set(), ["s"])
    assert learns.next_chat and len(learns.prompts) == 2
