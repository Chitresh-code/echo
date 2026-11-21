import pytest


@pytest.fixture(autouse=True)
def _signed_in(request):
    # These routes all need a signed-in user, so any test using the client gets one.
    if "client" in request.fixturenames:
        request.getfixturevalue("user")
