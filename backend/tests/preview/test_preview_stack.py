"""A server the agent starts, seen through its preview host, against the real runner and real
jails: run with `docker compose -f compose.test.yml run --rm api-test`."""

import asyncio
import time

import pytest

from core.config import get_settings
from sandbox import processes
from tests.preview.test_preview import agent, cookie_from, host, on, start  # noqa: F401 (fixtures)

pytestmark = pytest.mark.stack


def test_a_server_in_the_workspace_is_previewed(agent, client):  # noqa: F811
    agent_id, _ = agent
    try:
        # No user route starts a process, so this uses the same call as the agent's tool.
        asyncio.run(processes.start(get_settings().runner_socket, agent_id, "web", "printf '<p>from the jail</p>' > index.html && exec python3 -m http.server 3000"))
        deadline = time.monotonic() + 15
        while 3000 not in client.get(f"/api/agents/{agent_id}/processes").json()["data"]["ports"]:
            assert time.monotonic() < deadline, client.get(f"/api/agents/{agent_id}/processes/web/logs").text
            time.sleep(0.3)
        value = cookie_from(client, agent_id, start(client, agent_id)).split(";")[0]
        r = client.get("/index.html", headers={"host": host(agent_id), "cookie": value})
        assert r.status_code == 200 and "<p>from the jail</p>" in r.text, r.text
        assert r.headers["content-security-policy"] == "frame-ancestors http://testserver"
        # A port nothing listens on comes back from the runner, not as an api crash.
        value = cookie_from(client, agent_id, start(client, agent_id, 3001), 3001).split(";")[0]
        assert client.get("/", headers={"host": host(agent_id, 3001), "cookie": value}).status_code == 502
    finally:
        client.delete(f"/api/agents/{agent_id}")
