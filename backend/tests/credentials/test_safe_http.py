"""The custom endpoint client, with DNS answers patched and the real connect replaced, so no test
touches the network."""

import httpcore
import httpcore2
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
    monkeypatch.setattr(httpcore2.AnyIOBackend, "connect_tcp", connect_tcp)
    return State


# Both guarded clients: httpx for the model SDKs, httpx2 for the MCP SDK.
@pytest.fixture(params=["client", "client2"])
def fetch(request):
    async def fetch():
        async with getattr(safe_http, request.param)() as client:
            await client.get("https://endpoint.example/v1/models")
    return fetch


@pytest.mark.parametrize("answer", [
    ["127.0.0.1"], ["10.0.0.5"], ["172.16.0.1"], ["192.168.1.1"], ["169.254.169.254"], ["100.64.0.1"],
    ["0.0.0.0"], ["224.0.0.1"], ["::1"], ["::ffff:127.0.0.1"], ["fe80::1%eth0"], ["fd00::1"],
    ["93.184.216.34", "10.0.0.5"], [],
])
async def test_local_and_private_addresses_are_refused(dns, fetch, answer):
    dns.answer = answer
    with pytest.raises(safe_http.EndpointNotAllowed):
        await fetch()
    assert dns.connected == []


@pytest.mark.parametrize("answer", [["93.184.216.34"], ["2606:2800:220:1:248:1893:25c8:1946"]])
async def test_a_public_address_is_connected_to_as_checked(dns, fetch, answer):
    dns.answer, dns.connected = answer, []
    with pytest.raises(Connected):
        await fetch()
    assert dns.connected == answer[:1]


@pytest.mark.parametrize("make", [safe_http.client, safe_http.client2])
def test_no_proxies_and_no_redirects(make):
    client = make()
    assert client.follow_redirects is False and client._trust_env is False


async def test_client2_refuses_plain_http_before_connecting(dns):
    # Covers what an MCP server names for itself, such as an http token endpoint in its metadata.
    dns.answer, dns.connected = ["93.184.216.34"], []
    async with safe_http.client2() as client:
        with pytest.raises(safe_http.EndpointNotAllowed):
            await client.post("http://auth.example/token", data={"code": "c"})
    assert dns.connected == []


async def test_client2_checks_the_requests_an_auth_flow_sends(dns):
    import httpx2

    class TokenFirst(httpx2.Auth):
        def auth_flow(self, request):
            yield httpx2.Request("POST", "http://auth.example/token")
            yield request

    dns.answer, dns.connected = ["93.184.216.34"], []
    async with safe_http.client2(auth=TokenFirst()) as client:
        with pytest.raises(safe_http.EndpointNotAllowed):
            await client.get("https://mcp.example/mcp")
    assert dns.connected == []


def test_client2_carries_the_headers_and_auth_it_is_given():
    import httpx2
    auth = httpx2.BasicAuth("u", "p")
    client = safe_http.client2(headers={"X-Api-Key": "k"}, auth=auth)
    assert client.headers["X-Api-Key"] == "k" and client.auth is auth


def test_refused_finds_the_error_inside_exception_groups_and_chains():
    try:
        try:
            raise safe_http.EndpointNotAllowed("10.0.0.1")
        except Exception as inner:
            raise RuntimeError("connect failed") from inner
    except RuntimeError as chained:
        wrapped = ExceptionGroup("task group", [ValueError("other"), ExceptionGroup("nested", [chained])])
    assert safe_http.refused(wrapped)
    assert not safe_http.refused(ExceptionGroup("task group", [ValueError("other")]))
    looped = RuntimeError("a")
    looped.__context__ = RuntimeError("b")
    looped.__context__.__context__ = looped
    assert not safe_http.refused(looped)


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
