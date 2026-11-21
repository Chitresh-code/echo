import pytest
from fastapi.testclient import TestClient

from core.config import get_settings
from tests.helpers.fake_runner import FakeRunner


@pytest.fixture(scope="session")
def _fake_runner_server():
    runner = FakeRunner()
    runner.start()
    yield runner
    runner.stop()


@pytest.fixture
def fake_runner(_fake_runner_server):
    _fake_runner_server.reset()
    return _fake_runner_server


@pytest.fixture(autouse=True)
def settings_env(monkeypatch, tmp_path, request):
    monkeypatch.setenv("ECHO_MODELS", "anthropic/claude-sonnet-5-5,openai/gpt-5")
    monkeypatch.setenv("ECHO_DATA_DIR", str(tmp_path / "data"))
    # Stack tests talk to the real runner at the default socket; everything else gets the fake.
    if "stack" not in request.keywords:
        monkeypatch.setenv("ECHO_RUNNER_SOCKET", str(request.getfixturevalue("fake_runner").socket_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def app():
    from main import create_app

    return create_app()


@pytest.fixture
def client(app):
    # Unhandled errors must come back as the 500 envelope instead of being raised into the test.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
