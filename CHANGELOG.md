# Changelog

All notable changes to Echo are recorded here. The format follows Keep a Changelog, and versions follow semantic versioning (0.x until the first public release).

## Keeping this up to date

Every change adds a line under the current version heading (the newest one, marked "in progress") in the same change, in the group that fits: Added, Changed, Fixed, Removed or Security. Write it for someone running Echo, not as a commit message. When that version is released, replace "in progress" with the release date, open the next version heading above it marked "in progress", and set `version` in `backend/pyproject.toml` to the new number.

## 0.1.0 (in progress)

### Added
- Backend project with its dependency set: FastAPI, Strands harness, and Strands with the Anthropic, OpenAI and Gemini providers.
- api settings read once from the environment; startup fails when a required setting is missing or malformed, or the data directory is not writable.
- One response shape for every JSON success and error, with a request id in the body, the `X-Request-ID` header and every log line. Unexpected errors return a generic message and are logged in full, with provider keys masked.
- `GET /api/health`, and the generated API reference at `/api/docs` and `/api/openapi.json`.
- Runner service in the sandbox container: creates workspaces (a git repo with `.agent/skills/`) and runs each command in its own nsjail jail, streaming output as NDJSON over a Unix socket only the api's user can open. A jail sees only its workspace and its own persistent home, runs as uid 1000 with a time limit, and is killed when the caller disconnects. Commands of any length up to 8 MB run, so large file writes work.
- The api runs every workspace command through the runner, streaming output back as it arrives; leaving a command early stops its jail. The api refuses to start when the runner does not answer.
- Workspaces API: create and list workspaces, list a workspace's files, read and save files (text, or base64 for binary, up to 5 MB), git status, and a file's last committed and current versions for a diff. Every operation runs inside the workspace's jail. Bad ids and paths are refused before anything runs.
- Chat with the agent: start a chat in a workspace, and send a message that streams the agent's turn as server-sent events (`text`, `tool`, `done`, `error`). The agent's commands, file edits, skills and web fetches all run in the workspace's jail; a chat resumes its conversation on the next message, and the agent keeps notes per workspace. One turn at a time per chat (`chat_busy`), a turn stops at `ECHO_TURN_TIMEOUT`, and closing the request stops the turn and its running command. A failed turn reports a code and request id, never the provider's error text.
- User guide in `docs/` as plain HTML, served at `/docs`: an overview, getting started (registering Echo in Microsoft Entra, install, checking it runs), signing in (and using the session from `curl`), keys (adding your own provider key), workspaces (using them through the API) and chat (giving the agent a task with `curl`). A failed sign-in lands on the signing in page with its error code.
- The api keeps its own records in an SQLite database, `echo.db` in its data volume, and applies database migrations itself at startup.
- New required settings for accounts: `ECHO_PUBLIC_URL`, `ECHO_MS_TENANT_ID`, `ECHO_MS_CLIENT_ID`, `ECHO_MS_CLIENT_SECRET` and `ECHO_SECRET_KEY`. Startup fails when one is missing or malformed, without printing the secret values.
- Sign in with Microsoft: `GET /api/auth/login` signs in through your organization's Entra tenant and returns to the API reference with a session; `GET /api/auth/me` shows who is signed in and `POST /api/auth/logout` ends the session. Only accounts in the configured tenant are accepted, and a person is recognised by their Entra account, never by email. Sessions last 7 days.
- Workspaces belong to the user who created them: the list shows only your own, and someone else's workspace answers 404 `workspace_not_found`, the same as one that does not exist. Every workspace and chat route needs a signed-in user (401 `not_signed_in`).
- Your own model provider keys: `POST /api/credentials` adds an Anthropic, OpenAI, Google (AI Studio) or OpenAI-compatible key, `GET /api/credentials` lists them, `DELETE /api/credentials/{id}` removes one and `GET /api/credentials/{id}/models` lists the models it can use. A key is checked with the provider before it is stored, and only its last four characters are ever shown. A refused key answers `invalid_key`; other provider failures answer `provider_error` without the provider's text.
- A turn names the key and model it runs on: `credential_id` and `model` in the turn's body. A missing or someone else's key answers 404 `credential_not_found` before the turn starts. There is no server-wide model list or provider key any more: `ECHO_MODELS`, `ANTHROPIC_API_KEY` and the like are not read, and startup logs a warning when `ECHO_MODELS` is still set.
- api and sandbox images and `compose.yml`. The api runs unprivileged as a non-root user on 127.0.0.1; the sandbox image carries nsjail 3.4 and the toolchains jails use (Python 3.12, Node 22, uv, git, ripgrep, build tools).

### Security
- A POST, PUT, PATCH or DELETE whose `Origin` (or `Referer`) is not `ECHO_PUBLIC_URL` is refused with 403 `bad_origin`, so another site's page cannot act with a signed-in user's cookie. Open Echo at exactly that address. Clients like `curl` that send neither header are not affected.
- Sign-in uses the authorization code flow with PKCE, and the ID token's signature, audience, expiry, nonce, issuer and tenant are all checked. The session cookie is HttpOnly, SameSite=Lax and Secure when Echo is served over https; the database keeps only a hash of it. A failed sign-in tells the browser only an error code.
- Provider keys are stored encrypted with `ECHO_SECRET_KEY` and never returned. Changing that key makes stored keys unreadable (`credential_unreadable`), so they must be added again.
- A custom endpoint must be https, with no user name in the address. Echo resolves its host when connecting and refuses loopback, private, link-local (cloud metadata), carrier-grade NAT, multicast and reserved addresses (`endpoint_not_allowed`), then connects to the address it checked. It ignores proxy settings and follows no redirects.
- The agent's web fetches run with `curl` inside the jail, behind its firewall, never from the api. The harness tool that runs model-written Python inside the api process is turned off, so no agent-written code runs next to the provider keys.
- Jails reach the internet behind a firewall on the jail user that allows DNS to the configured resolvers and rejects loopback, private, carrier-grade NAT, link-local (cloud metadata), multicast and IPv4-mapped addresses. The sandbox refuses to start if the firewall cannot be installed.
- The api and sandbox containers are on separate networks and share only the runner's socket, so nothing in the sandbox container has a network path to the api.
