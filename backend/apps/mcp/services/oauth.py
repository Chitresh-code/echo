"""OAuth for remote MCP servers, on top of the MCP SDK's client, which already does discovery in the
spec's order, issuer checks, registration bound to the issuer, the `resource` parameter, the RFC 9207
`iss` check and the scope union on step-up. Echo adds what a hosted client needs:

- Tokens and the registered client live in the server's encrypted secret, not in a file.
- Connecting is split over two requests: one starts the flow and returns the authorization URL, the
  provider's redirect comes back to a callback that finishes it. A flow in between waits here, in
  memory, under its `state`, for at most FLOW_SECONDS.
- In a turn nobody can be sent to a browser, so a provider that needs a new authorization records
  why (`needs`) and fails the request instead; the server is then marked to be connected again."""

import asyncio
import logging
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from mcp.client.auth import OAuthClientProvider, OAuthFlowError
from mcp.client.auth.utils import union_scopes
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)

from core.config import Settings
from core.errors import AppError

logger = logging.getLogger(__name__)

CALLBACK_PATH = "/api/mcp/oauth/callback"
CLIENT_PATH = "/api/mcp/oauth/client"
# How long a user has to approve at the provider before the flow is dropped.
FLOW_SECONDS = 600
# Discovery and registration before the authorization URL exists.
URL_SECONDS = 20
# Exchanging the code and listing the tools once the user is back.
FINISH_SECONDS = 30
MAX_FLOWS_PER_USER = 3


class Unsupported(OAuthFlowError):
    """The authorization server lacks a protection the MCP spec requires of it."""


class NeedsAuth(OAuthFlowError):
    pass


def client_metadata(settings: Settings, confidential: bool = False) -> OAuthClientMetadata:
    return OAuthClientMetadata(
        client_name="Echo",
        client_uri=settings.public_url,
        redirect_uris=[settings.public_url + CALLBACK_PATH],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="client_secret_post" if confidential else "none",
        application_type="web",
    )


def client_metadata_url(settings: Settings) -> str | None:
    # An authorization server fetches this document, so it only works when Echo is public over
    # https; otherwise the server registers Echo instead.
    return settings.public_url + CLIENT_PATH if settings.public_url.startswith("https://") else None


def metadata_document(settings: Settings) -> dict:
    """The client ID metadata document; its client_id must be its own URL."""
    document = client_metadata(settings).model_dump(mode="json", exclude_none=True)
    return {"client_id": settings.public_url + CLIENT_PATH, **document}


class Store:
    """The SDK's token storage over the OAuth part of a server's secret. `changed` says whether it
    must be written back."""

    def __init__(self, blob: dict, redirect_uri: str):
        self.blob, self.redirect_uri, self.changed = blob, redirect_uri, False
        self.context = None

    async def get_tokens(self) -> OAuthToken | None:
        return OAuthToken.model_validate(self.blob["tokens"]) if "tokens" in self.blob else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.blob["tokens"] = tokens.model_dump(mode="json", exclude_none=True)
        # Kept as a time, since expires_in means nothing once read back later.
        self.blob["expires_at"] = time.time() + tokens.expires_in if tokens.expires_in else None
        # What discovery found, kept with the tokens: a turn refreshes without discovering again,
        # and the SDK would otherwise guess the token endpoint from the MCP server's address.
        if self.context is not None and self.context.oauth_metadata is not None:
            self.blob["discovered"] = {
                "auth_server_url": self.context.auth_server_url,
                "oauth": self.context.oauth_metadata.model_dump(mode="json", exclude_none=True),
                "resource": self.context.protected_resource_metadata.model_dump(mode="json", exclude_none=True)
                if self.context.protected_resource_metadata else None,
            }
        self.changed = True

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        if "client" in self.blob:
            return OAuthClientInformationFull.model_validate(self.blob["client"])
        if pre := self.blob.get("preregistered"):
            method = "client_secret_post" if pre.get("client_secret") else "none"
            return OAuthClientInformationFull(**pre, token_endpoint_auth_method=method, redirect_uris=[self.redirect_uri])
        return None

    async def set_client_info(self, info: OAuthClientInformationFull) -> None:
        self.blob["client"] = info.model_dump(mode="json", exclude_none=True)
        self.changed = True


class Guarded(OAuthClientProvider):
    """The SDK's provider, refusing an authorization server without PKCE S256 or an https
    authorization endpoint, and asking for at least the scopes the server needed before."""

    def __init__(self, server_name: str, url: str, settings: Settings, blob: dict, redirect=None, callback=None):
        self.server_name = server_name
        self.store = Store(blob, settings.public_url + CALLBACK_PATH)
        # Why a turn's provider gave up: "needs_auth" or "needs_scope".
        self.needs: str | None = None
        confidential = bool(blob.get("preregistered", {}).get("client_secret"))
        super().__init__(
            url, client_metadata(settings, confidential), self.store, redirect or self._cannot_redirect, callback or self._no_callback,
            client_metadata_url(settings),
        )
        self.store.context = self.context

    async def _initialize(self) -> None:
        await super()._initialize()
        self.context.token_expiry_time = self.store.blob.get("expires_at")
        if found := self.store.blob.get("discovered"):
            self.context.auth_server_url = found["auth_server_url"]
            self.context.oauth_metadata = OAuthMetadata.model_validate(found["oauth"])
            if found["resource"]:
                self.context.protected_resource_metadata = ProtectedResourceMetadata.model_validate(found["resource"])

    async def _perform_authorization_code_grant(self) -> tuple[str, str]:
        meta = self.context.oauth_metadata
        if meta is None or "S256" not in (meta.code_challenge_methods_supported or []):
            raise Unsupported("The authorization server does not offer PKCE with S256.")
        if meta.authorization_endpoint.scheme != "https":
            raise Unsupported("The authorization endpoint is not https.")
        self.context.client_metadata.scope = union_scopes(self.context.client_metadata.scope, self.store.blob.get("scope"))
        return await super()._perform_authorization_code_grant()

    async def _cannot_redirect(self, url: str) -> None:
        wanted = set(parse_qs(urlparse(url).query).get("scope", [""])[0].split())
        granted = set((self.context.current_tokens.scope or "").split()) if self.context.current_tokens else None
        # Still holding tokens, and asked for scopes beyond them: a step-up, not a lost sign-in.
        self.needs = "needs_scope" if granted is not None and not wanted <= granted else "needs_auth"
        if wanted:
            self.store.blob["scope"] = " ".join(sorted(wanted))
            self.store.changed = True
        raise NeedsAuth(f"{self.server_name} must be connected again")

    async def _no_callback(self) -> AuthorizationCodeResult:
        raise NeedsAuth(f"{self.server_name} must be connected again")


@dataclass
class Flow:
    user_id: str
    server_id: str
    task: asyncio.Task
    code: asyncio.Future
    provider: Guarded
    expires: float


_flows: dict[str, Flow] = {}


def _drop(state: str) -> None:
    if flow := _flows.pop(state, None):
        flow.task.cancel()


def _expire() -> None:
    now = time.monotonic()
    for state in [s for s, f in _flows.items() if f.expires < now or f.task.done()]:
        _drop(state)


async def start(user_id: str, server_id: str, provider: Guarded, connect) -> str:
    """Runs `connect(provider)` (a connect and tool list) in the background until the provider has
    an authorization URL, and returns it. Raises what the connection raised if it ends first."""
    _expire()
    for state in [s for s, f in _flows.items() if f.user_id == user_id and f.server_id == server_id]:
        _drop(state)
    if sum(f.user_id == user_id for f in _flows.values()) >= MAX_FLOWS_PER_USER:
        raise AppError(429, "too_many_oauth_flows", f"You have {MAX_FLOWS_PER_USER} connections waiting for approval. Finish or close one, then try again.")

    loop = asyncio.get_running_loop()
    url, code = loop.create_future(), loop.create_future()

    async def redirect(authorize_url: str) -> None:
        if not url.done():
            url.set_result(authorize_url)

    async def callback() -> AuthorizationCodeResult:
        return await asyncio.wait_for(code, FLOW_SECONDS)

    provider.context.redirect_handler, provider.context.callback_handler = redirect, callback
    task = asyncio.create_task(connect(provider))
    await asyncio.wait({url, task}, timeout=URL_SECONDS, return_when=asyncio.FIRST_COMPLETED)
    if not url.done():
        task.cancel()
        if task.done() and not task.cancelled() and task.exception() is not None:
            raise task.exception()
        if task.done():
            raise AppError(400, "oauth_not_needed", "The server answered without asking to sign in. Change its sign-in to none or headers.")
        raise AppError(502, "mcp_server_error", f"The server did not start the sign-in within {URL_SECONDS} seconds. Try again later.")
    state = parse_qs(urlparse(url.result()).query)["state"][0]
    _flows[state] = Flow(user_id, server_id, task, code, provider, time.monotonic() + FLOW_SECONDS)
    return url.result()


def _invalid() -> AppError:
    return AppError(400, "oauth_state_invalid", "This sign-in link has expired or was already used. Start connecting again.")


async def finish(user_id: str, state: str, code: str | None, iss: str | None, error: str | None) -> tuple[Flow, list[dict]]:
    """Hands the code to the waiting flow and returns it with the tools it listed. Raises what the
    exchange or the connection raised."""
    _expire()
    flow = _flows.get(state)
    if flow is None or flow.user_id != user_id:
        raise _invalid()
    del _flows[state]
    if error or not code:
        flow.task.cancel()
        # The provider's own description is never shown: it is text from another site.
        raise AppError(400, "oauth_denied", "The sign-in was declined or cancelled at the provider.")
    flow.code.set_result(AuthorizationCodeResult(code=code, state=state, iss=iss))
    try:
        listed = await asyncio.wait_for(flow.task, FINISH_SECONDS)
    except TimeoutError:
        raise AppError(502, "mcp_server_error", "The server did not finish the sign-in in time. Try connecting again.") from None
    return flow, listed
