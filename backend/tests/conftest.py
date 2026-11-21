import pytest
from fastapi.testclient import TestClient

from core.config import get_settings
from tests.helpers.fake_runner import FakeRunner

# Valid but fake values for the required settings. The key is a fixed test-only Fernet key.
TEST_ENV = {
    "ECHO_PUBLIC_URL": "http://testserver",
    "ECHO_MS_TENANT_ID": "11111111-1111-1111-1111-111111111111",
    "ECHO_MS_CLIENT_ID": "22222222-2222-2222-2222-222222222222",
    "ECHO_MS_CLIENT_SECRET": "test-client-secret",
    "ECHO_SECRET_KEY": "dGVzdC1vbmx5LWtleS1ub3QtYS1zZWNyZXQtMDAwMDA=",
}


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
    monkeypatch.setenv("ECHO_DATA_DIR", str(tmp_path / "data"))
    for name, value in TEST_ENV.items():
        monkeypatch.setenv(name, value)
    # Stack tests talk to the real runner at the default socket; everything else gets the fake.
    if "stack" not in request.keywords:
        monkeypatch.setenv("ECHO_RUNNER_SOCKET", str(request.getfixturevalue("fake_runner").socket_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_local_web_build(settings_env, monkeypatch, tmp_path):
    # Imported after the settings, since importing main builds an app. A web/dist built on this machine would add the app's catch-all route; tests that want it
    # pass their own build to create_app.
    import main

    monkeypatch.setattr(main, "WEB_DIR", tmp_path / "no-web-build")


@pytest.fixture
def app():
    from main import create_app

    return create_app()


@pytest.fixture
def client(app):
    # Unhandled errors must come back as the 500 envelope instead of being raised into the test.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def user(client):
    """The id of the user `client` is signed in as."""
    from tests.helpers.accounts import sign_in_as

    return sign_in_as(client)
