import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, SecretStr, StringConstraints, model_validator

from core.db import UtcDateTime

Kind = Literal["remote", "local"]
Auth = Literal["none", "headers", "oauth"]
# ok: usable. needs_auth: OAuth with no usable tokens. needs_scope: the server asked for more access
# than was granted. tools_changed: the server's tools differ from the reviewed ones, so it is left
# out of turns until the user reviews them.
Status = Literal["ok", "needs_auth", "needs_scope", "tools_changed"]

# The prefix of every tool the server offers, so it must be short and safe in a tool name.
ServerName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,19}$")]
SecretValue = Annotated[SecretStr, Field(min_length=1, max_length=4000)]
Arg = Annotated[str, StringConstraints(max_length=1000)]

MAX_HEADERS = 10
MAX_ENV = 20
# HTTP token characters, as a header name allows.
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,100}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def check_headers(headers: dict[str, SecretStr], oauth: bool = False) -> None:
    """Header names a user may set: not ones the transport owns, which would break or redirect the
    connection, and not Authorization when OAuth sets it."""
    if len(headers) > MAX_HEADERS:
        raise ValueError(f"At most {MAX_HEADERS} headers.")
    for name, value in headers.items():
        lower = name.lower()
        if not _HEADER_NAME.match(name):
            raise ValueError(f"{name!r} is not a valid header name.")
        if lower in ("host", "content-length", "transfer-encoding", "connection") or lower.startswith("mcp-") or (oauth and lower == "authorization"):
            raise ValueError(f"The {name} header is set by Echo and cannot be given.")
        if any(c in value.get_secret_value() for c in "\r\n\0"):
            raise ValueError(f"The {name} header's value has a line break.")


def check_env(env: dict[str, SecretStr]) -> None:
    if len(env) > MAX_ENV:
        raise ValueError(f"At most {MAX_ENV} environment variables.")
    for name, value in env.items():
        if not _ENV_NAME.match(name):
            raise ValueError(f"{name!r} is not a valid environment variable name.")
        if "\0" in value.get_secret_value():
            raise ValueError(f"The {name} variable's value has a null character.")


class NewMcpServer(BaseModel):
    name: ServerName = Field(description="Lower case letters, digits and underscores, starting with a letter; its tools are offered as <name>_<tool>")
    kind: Kind
    url: str | None = Field(None, max_length=500, description="Remote only: the server's https address")
    auth: Auth | None = Field(None, description="Remote only: none, headers (sent with every request) or oauth")
    # SecretStr keeps the values out of reprs and logs.
    headers: dict[str, SecretValue] | None = Field(None, description="Remote with auth headers: header names and values, such as an API key")
    client_id: str | None = Field(None, min_length=1, max_length=500, description="Remote with auth oauth: a client registered with the server's authorization server, when it does not register clients itself")
    client_secret: SecretValue | None = None
    command: str | None = Field(None, min_length=1, max_length=500, description="Local only: the program to start in the workspace, such as npx")
    args: list[Arg] | None = Field(None, max_length=50)
    env: dict[str, SecretValue] | None = Field(None, description="Local only: environment variables for the server, such as an API key")

    @model_validator(mode="after")
    def _fits_its_kind(self):
        def refuse(**fields):
            given = [name for name, value in fields.items() if value is not None]
            if given:
                raise ValueError(f"A {self.kind} server does not take {', '.join(given)}.")

        if self.kind == "remote":
            refuse(command=self.command, args=self.args, env=self.env)
            if not self.url or not self.auth:
                raise ValueError("A remote server needs url and auth.")
            if self.auth != "headers":
                refuse(headers=self.headers)
            elif not self.headers:
                raise ValueError("auth headers needs at least one header.")
            else:
                check_headers(self.headers)
            if self.auth != "oauth":
                refuse(client_id=self.client_id, client_secret=self.client_secret)
            elif self.client_secret is not None and self.client_id is None:
                raise ValueError("client_secret needs a client_id.")
        else:
            refuse(url=self.url, auth=self.auth, headers=self.headers, client_id=self.client_id, client_secret=self.client_secret)
            if not self.command:
                raise ValueError("A local server needs a command.")
            check_env(self.env or {})
        return self


class McpTool(BaseModel):
    name: str
    description: str
    # The server's hints about the tool, such as readOnlyHint. A server can claim anything, so they
    # are shown to the user and never decide whether a call needs approval.
    hints: dict | None = None


class McpServer(BaseModel):
    """A server as the API shows it: the names of its headers and variables, never their values."""

    id: str
    name: str
    kind: Kind
    url: str | None
    auth: Auth | None
    command: str | None
    args: list[str] | None
    header_names: list[str]
    env_names: list[str]
    # OAuth with a client the user registered themselves.
    preregistered: bool
    status: Status
    tools: list[McpTool]
    # The changed tools a turn found, waiting for review, and the hash that accepts them.
    pending_tools: list[McpTool] | None
    pending_hash: str | None
    created_at: UtcDateTime


class SecretUpdate(BaseModel):
    """Replaces a server's whole set of headers (remote with auth headers) or variables (local)."""

    headers: dict[str, SecretValue] | None = None
    env: dict[str, SecretValue] | None = None

    @model_validator(mode="after")
    def _one(self):
        if (self.headers is None) == (self.env is None):
            raise ValueError("Give either headers or env.")
        if self.headers is not None:
            if not self.headers:
                raise ValueError("auth headers needs at least one header.")
            check_headers(self.headers)
        if self.env is not None:
            check_env(self.env)
        return self


class AgentServers(BaseModel):
    server_ids: list[Annotated[str, StringConstraints(max_length=64)]] = Field(max_length=100)


class ToolReview(BaseModel):
    hash: str = Field(min_length=64, max_length=64, description="The pending_hash of the tools being accepted")


class OAuthStart(BaseModel):
    authorize_url: str
