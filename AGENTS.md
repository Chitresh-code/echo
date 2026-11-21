# AGENTS.md

This file gives coding agents (Claude Code and others) the guidance they need to work in this repository.

## Overview

Echo is a hosted coding and workspace agent used from the browser. Each user works in workspaces that look like a small IDE (file tree, editor, git diff, chat), and an agent does the work inside an isolated jail per workspace. The agent keeps notes and skills per workspace, so it gets better at the workflows each user repeats.

Services, each its own container:
- `backend/` is the api: FastAPI on Python 3.12, managed with `uv` (`pyproject.toml`, `uv.lock`). It serves the browser, holds the model provider keys and runs the agent, which is Strands harness (`strands-harness`). Models are chosen by `provider/model` strings, including any LiteLLM model through `litellm/<model>`, so no provider is hard wired. Runs unprivileged.
- `runner/` is the sandbox service. It owns the workspaces and starts an nsjail jail per command, on demand. Runs privileged and holds no secrets.
- `web/` (not created yet) will be the React + Vite + Monaco frontend.

So far the backend has its core plumbing and a health check, and the runner creates workspaces and runs jailed commands. The backend has the Workspaces API (`backend/apps/workspaces/`), which reaches the runner through `RunnerSandbox`. Chat lives in `backend/apps/chat/`: `agent_factory.py` builds the Strands harness agent for one turn with the workspace's `RunnerSandbox`, and `turn_service.py` runs it as a task that streams server-sent events. Tests drive turns with `tests/helpers/scripted_model.py`, a model that plays back fixed replies, so no test calls a provider. The agent's model choice, tools and instructions are a basic first version, to be refined one piece at a time. Known shortcuts carry a `shortcut:` comment saying the limit and when to lift it; list them with `grep -rn "shortcut:" backend runner`.

## Commands

### Backend (from `backend/`)
```bash
uv sync                  # install dependencies
uv run pytest            # unit tests against a fake runner on a temporary socket; tests marked `stack` are skipped
uv run uvicorn main:app --reload   # needs ECHO_MODELS, and ECHO_RUNNER_SOCKET pointing at a running runner, or startup fails
```

### Stack (from the repo root)
```bash
cp .env.example .env     # then set ECHO_MODELS and provider keys
docker compose build
docker compose up        # api on 127.0.0.1:${ECHO_PORT:-8000}, user guide at /docs, API reference at /api/docs
docker compose --profile test run --rm api-test       # backend tests inside the api image, including `stack` tests against the real runner
docker compose --profile test run --rm sandbox-test   # runner tests, including real jails behind the firewall
```

### Runner (from `runner/`)
```bash
uv run pytest            # unit tests with a stand-in nsjail; tests marked `jail` only run in the sandbox image
```

## Architecture notes

**Backend layout**: shared plumbing lives in `backend/core/` (the single settings accessor `config.py`, `AppError` and safe messages, error handlers, the response envelope, request ids, logging). Each domain is a folder under `backend/apps/` split into `routers/`, `services/` and `models/` (and `repositories/` once there is a database). Services stay thin and delegate to small plain-function modules, and pure parsing and mapping live apart from I/O so they can be tested with plain values. Tests under `backend/tests/` are grouped the same way.

**API shape**: every JSON success is `{"success": true, "data": ..., "meta": {"request_id"}}` and every error is `{"success": false, "error": {"code", "message", "details"}, "meta": {"request_id"}}`. Endpoints return their data and the default response class wraps it. Only `AppError` messages reach a caller; anything else becomes a generic message and goes to the log. Streams are not wrapped.

**User guide**: `docs/` holds the end user guide as plain HTML pages with one shared `style.css`, served by the api at `/docs` with no build step. It describes only what is built, never what is planned, and a change that adds or alters something a user sees updates the guide in the same change. Pages link to each other relatively, except `404.html`, which uses absolute `/docs/` links because it is served at any missing path.

**API docs**: FastAPI's generated docs at `/api/docs` and `/api/openapi.json` are the only API reference. There is no hand-kept collection or committed schema, so every route declares its request and response models and a summary.

**Sandbox**: every command the agent runs and every file operation, including the ones the UI makes (file tree, open, save, git status and diff), goes to the runner, which runs it in that workspace's nsjail jail. In the api this is `RunnerSandbox` (`backend/sandbox/runner_sandbox.py`), a Strands `PosixShellSandbox` that talks to the runner over a Unix socket on a volume shared only by the two containers. The runner writes each command to a read-only file under `/data/commands/` that is bind mounted into the jail at the same path, because Linux limits one argument to 128 KB and file writes carry their content inside the command. A jail sees only its own workspace (at the same absolute path it has in the sandbox container, so paths mean the same thing everywhere) and its own home at `/home/echo`, read-only system directories, a private `/tmp` and no inherited environment. Its network is the sandbox container's, behind a firewall on uid 1000 that allows DNS and public addresses and rejects loopback, private, metadata and link-local ranges. The two containers are on separate networks and share only the socket volume; the socket is mode 0600 and owned by the api's uid 10001. The firewall is installed by `runner/entrypoint.sh`, which fails the container if any rule fails. The api container has no workspace files: never add a path from the api to a workspace, because a user controls everything in it, including symlinks.

**Agent state**: Strands harness writes conversation sessions and long-term memory from the api process, so they live in the api container's data directory, keyed by workspace id. Skills are read through the sandbox, so they live in the workspace under `.agent/skills/`, where the agent and the user can both edit them.

**nsjail needs Linux**: namespaces only exist on Linux, so local development and production both run in containers via `compose.yml`, and only the sandbox container is privileged.

## Working with this repo

**Plan before you build.** Before implementing a feature or any non-trivial change, write down the approach and wait for explicit approval before writing code.

**No quick fixes.** Find the root cause and fix it the way it should exist in production, even when that touches more than the line a bug report points at.

**Security is not optional.** For every new endpoint or tool, check tenant isolation (can one user reach another's workspace, session or memory), sandbox escape paths, injection, SSRF and secrets handling before calling it done. Model provider keys stay in the api container and never reach the sandbox container or a jail.

**Keep the changelog current.** Every change adds a line under the current version heading in `CHANGELOG.md` (the newest one, marked "in progress") in the same change. There is no "Unreleased" section. On release, "in progress" becomes the release date, the next version heading opens above it, and `version` in `backend/pyproject.toml` is set to the new number.

**Consistent API shapes.** Before adding an endpoint, check how sibling endpoints shape success and error responses and match them.

**Dependencies.** Prefer what the standard library, the platform or an installed dependency already gives. Pin new dependencies through `uv add` so `uv.lock` records the exact version.

## Writing and documentation style

- No em dashes, anywhere.
- Do not hard-wrap paragraphs inside documents.
- Write in a plain, human style, not AI-assistant-flavored language.
- No emojis in code, comments, commit messages or docs.
- Comment the reasoning behind non-obvious logic. Comments explain the code on their own terms and never reference documents outside this repository.
