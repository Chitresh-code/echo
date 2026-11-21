"""The custom endpoint client, with DNS answers patched and the real connect replaced, so no test
touches the network."""

import httpcore
import pytest

from apps.credentials.services import providers, safe_http
from core.errors import AppError


class Connected(Exception):
    pass


@pytest.fixture
def dns(monkeypatch):
    """Set `dns.answer` to what the host resolves to; `dns.connected` records where a connection went."""

    class State:
        answer: list[str] = []
        connected: list[str] = []

    async def getaddrinfo(host, port):
        return State.answer

    async def connect_tcp(self, host, port, *args, **kwargs):
        State.connected.append(host)
        raise Connected

    monkeypatch.setattr(safe_http, "_getaddrinfo", getaddrinfo)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect_tcp)
    return State


async def fetch():
    async with safe_http.client() as client:
        await client.get("https://endpoint.example/v1/models")


@pytest.mark.parametrize("answer", [
    ["127.0.0.1"], ["10.0.0.5"], ["172.16.0.1"], ["192.168.1.1"], ["169.254.169.254"], ["100.64.0.1"],
    ["0.0.0.0"], ["224.0.0.1"], ["::1"], ["::ffff:127.0.0.1"], ["fe80::1%eth0"], ["fd00::1"],
    ["93.184.216.34", "10.0.0.5"], [],
])
async def test_local_and_private_addresses_are_refused(dns, answer):
    dns.answer = answer
    with pytest.raises(safe_http.EndpointNotAllowed):
        await fetch()
    assert dns.connected == []


@pytest.mark.parametrize("answer", [["93.184.216.34"], ["2606:2800:220:1:248:1893:25c8:1946"]])
async def test_a_public_address_is_connected_to_as_checked(dns, answer):
    dns.answer, dns.connected = answer, []
    with pytest.raises(Connected):
        await fetch()
    assert dns.connected == answer[:1]


def test_no_proxies_and_no_redirects():
    client = safe_http.client()
    assert client.follow_redirects is False and client._trust_env is False


async def test_a_refused_endpoint_maps_to_its_own_error_through_the_sdk(dns):
    dns.answer = ["169.254.169.254"]
    with pytest.raises(AppError) as raised:
        await providers.list_models("openai_compatible", "sk-test", "https://endpoint.example/v1")
    assert raised.value.code == "endpoint_not_allowed"


async def test_every_model_request_gets_a_fresh_guarded_client():
    model = providers.build_model("openai_compatible", "sk-test", "https://endpoint.example/v1", "m")
    seen = []
    for _ in range(2):
        async with model._get_client() as client:
            seen.append(client._client)
            assert isinstance(client._client._transport._pool._network_backend, safe_http._CheckedBackend)
    assert seen[0] is not seen[1] and seen[0].is_closed


@pytest.mark.parametrize("url", [
    None, "", "http://api.example.com/v1", "https://", "https://user:pw@api.example.com",
    "https://api.example.com/v1?x=1", "https://api.example.com/v1#f", "ftp://api.example.com",
])
def test_bad_base_urls(url):
    with pytest.raises(AppError) as raised:
        safe_http.check_base_url(url)
    assert raised.value.code == "invalid_base_url"


def test_good_base_url():
    assert safe_http.check_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"
