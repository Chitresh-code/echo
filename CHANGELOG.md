# Changelog

All notable changes to Echo are recorded here. The format follows Keep a Changelog, and versions follow semantic versioning (0.x until the first public release).

## Keeping this up to date

Every change adds a line under the current version heading (the newest one, marked "in progress") in the same change, in the group that fits: Added, Changed, Fixed, Removed or Security. Write it for someone running Echo, not as a commit message. When that version is released, replace "in progress" with the release date, open the next version heading above it marked "in progress", and set `version` in `backend/pyproject.toml` to the new number.

## 0.1.0 (in progress)

### Added
- Backend project with its dependency set: FastAPI, Strands harness, and Strands with the LiteLLM provider.
- api settings read once from the environment; startup fails when `ECHO_MODELS` is missing or malformed, or the data directory is not writable.
- One response shape for every JSON success and error, with a request id in the body, the `X-Request-ID` header and every log line. Unexpected errors return a generic message and are logged in full, with provider keys masked.
- `GET /api/health`, and the generated API reference at `/api/docs` and `/api/openapi.json`.
- Runner service in the sandbox container: creates workspaces (a git repo with `.agent/skills/`) and runs each command in its own nsjail jail, streaming output as NDJSON over a Unix socket only the api's user can open. A jail sees only its workspace and its own persistent home, runs as uid 1000 with a time limit, and is killed when the caller disconnects. Commands of any length up to 8 MB run, so large file writes work.
- The api runs every workspace command through the runner, streaming output back as it arrives; leaving a command early stops its jail. The api refuses to start when the runner does not answer.
- Workspaces API: create and list workspaces, list a workspace's files, read and save files (text, or base64 for binary, up to 5 MB), git status, and a file's last committed and current versions for a diff. Every operation runs inside the workspace's jail. Bad ids and paths are refused before anything runs.
- Chat with the agent: `GET /api/models`, start a chat in a workspace, and send a message that streams the agent's turn as server-sent events (`text`, `tool`, `done`, `error`). The agent's commands, file edits, skills and web fetches all run in the workspace's jail; a chat resumes its conversation on the next message, and the agent keeps notes per workspace. One turn at a time per chat (`chat_busy`), a turn stops at `ECHO_TURN_TIMEOUT`, and closing the request stops the turn and its running command. A failed turn reports a code and request id, never the provider's error text.
- The Anthropic, OpenAI and Google providers are installed alongside LiteLLM, and the api refuses to start when an `ECHO_MODELS` entry names a provider it cannot build.
- User guide in `docs/` as plain HTML, served at `/docs`: an overview, getting started (install, choosing models, checking it runs), workspaces (using them through the API) and chat (giving the agent a task with `curl`).
- api and sandbox images and `compose.yml`. The api runs unprivileged as a non-root user on 127.0.0.1; the sandbox image carries nsjail 3.4 and the toolchains jails use (Python 3.12, Node 22, uv, git, ripgrep, build tools).

### Security
- The agent's web fetches run with `curl` inside the jail, behind its firewall, never from the api. The harness tool that runs model-written Python inside the api process is turned off, so no agent-written code runs next to the provider keys.
- Jails reach the internet behind a firewall on the jail user that allows DNS to the configured resolvers and rejects loopback, private, carrier-grade NAT, link-local (cloud metadata), multicast and IPv4-mapped addresses. The sandbox refuses to start if the firewall cannot be installed.
- The api and sandbox containers are on separate networks and share only the runner's socket, so nothing in the sandbox container has a network path to the api.
