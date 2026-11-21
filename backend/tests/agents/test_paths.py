import pytest

from apps.agents.services.paths import check_agent_id, safe_relpath
from core.errors import AppError


@pytest.mark.parametrize("path,expected", [("a.txt", "a.txt"), ("src/app/main.py", "src/app/main.py"), ("./src//x", "src/x"), ("dir/", "dir"), ("my file.md", "my file.md"), ("-rf", "-rf")])
def test_safe_relpath_accepts(path, expected):
    assert safe_relpath(path) == expected


@pytest.mark.parametrize("path", ["", "/etc/passwd", "../x", "a/../../x", "a/..", "a\0b", ".", "./"])
def test_safe_relpath_rejects(path):
    with pytest.raises(AppError) as e:
        safe_relpath(path)
    assert (e.value.status_code, e.value.code) == (400, "invalid_path")


@pytest.mark.parametrize("bad", ["", "A" * 32, "a" * 31, "a" * 33, "g" * 32, "../" + "a" * 29])
def test_agent_id_rejects(bad):
    with pytest.raises(AppError):
        check_agent_id(bad)
    assert check_agent_id("0123456789abcdef" * 2)
