from apps.agents.services.git_status import parse_porcelain


def test_parses_each_kind_of_change():
    output = "?? new file.txt\0 M src/app.py\0 D gone.txt\0R  new name.py\0old name.py\0A  added.md\0"
    assert [e.model_dump() for e in parse_porcelain(output)] == [
        {"path": "new file.txt", "index": "?", "worktree": "?", "original_path": None},
        {"path": "src/app.py", "index": " ", "worktree": "M", "original_path": None},
        {"path": "gone.txt", "index": " ", "worktree": "D", "original_path": None},
        {"path": "new name.py", "index": "R", "worktree": " ", "original_path": "old name.py"},
        {"path": "added.md", "index": "A", "worktree": " ", "original_path": None},
    ]


def test_clean_tree_is_empty():
    assert parse_porcelain("") == []
