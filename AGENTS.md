# AGENTS.md

This file gives coding agents (Claude Code and others) the guidance they need to work in this repository.

## Overview

Echo gives each user agents that each learn one job from them and keep what they learn. A user creates an agent with a name and a job, shows it the job in a chat and corrects it; the agent writes the workflows it learns into skills and keeps notes, so it gets better at that job. The coding sandbox is the baseline every agent runs on: each agent has a workspace (a git repository) and does its work there inside an isolated jail. In code and the API the thing a user creates is an agent; its folder in the sandbox is its workspace, which is why the runner, the sandbox volume and the data folders still say workspace.

Services, each its own container:
- `backend/` is the api: FastAPI on Python 3.12, managed with `uv` (`pyproject.toml`, `uv.lock`). It serves the browser, keeps each user's model provider keys encrypted, and runs the agent, which is Strands harness (`strands-harness`). A turn names one of the user's keys and a model that key can use; Anthropic, OpenAI, Google and OpenAI-compatible endpoints are supported. Runs unprivileged.
- `runner/` is the sandbox service. It owns the workspaces and starts an nsjail jail per command, on demand. Runs privileged and holds no secrets.
- `web/` is the browser app: React, TypeScript, Vite, MUI and a bundled Monaco. The api image builds it in a Node stage and the api serves it at `/`, on the same origin as the API, so the session cookie and the Origin check need nothing extra.

So far the backend has its core plumbing and a health check, and the runner creates workspaces and runs jailed commands. Users sign in with Microsoft Entra (`backend/apps/accounts/`), and the api keeps its records in SQLite through SQLAlchemy, migrated with Alembic at startup (`core/db.py`, `migrations/`). Users store their own provider keys encrypted (`backend/apps/credentials/`). The backend has the Agents API (`backend/apps/agents/`), each agent owned by one user, which reaches the agent's workspace through `RunnerSandbox`. Chat lives in `backend/apps/chat/`: `agent_factory.py` builds the Strands harness agent for one turn with the agent's `RunnerSandbox`, and `turn_service.py` runs it as a task that streams server-sent events. Tests drive turns with `tests/helpers/scripted_model.py`, a model that plays back fixed replies, so no test calls a provider, and sign a test client in with `tests/helpers/accounts.py` instead of going through Microsoft. `agent_factory.py` also holds the agent's instructions and its tool set; after changing either, run the evals in `backend/evals/`. Known shortcuts carry a `shortcut:` comment saying the limit and when to lift it; list them with `grep -rn "shortcut:" backend runner`.

## Commands

### Backend (from `backend/`)
```bash
uv sync                  # install dependencies
uv run pytest            # unit tests against a fake runner on a temporary socket; tests marked `stack` are skipped
uv run uvicorn main:app --reload   # needs the account settings in .env.example and ECHO_RUNNER_SOCKET pointing at a running runner, or startup fails
ECHO_DATA_DIR=/tmp/echo-dev uv run alembic revision -m "what it changes"   # new migration in migrations/versions/; the api applies migrations at startup
```

Evals (`backend/evals/`, see its README) run real tasks against a running Echo on your own key and cost money; run them by hand after changing the agent's tools or instructions, never in CI:
```bash
ECHO_SESSION=<cookie> uv run python -m evals.run --credential <key id> --model claude-haiku-5-5 --effort low --max-tokens 400000
```

### Stack (from the repo root)
```bash
cp .env.example .env     # then set the account settings
docker compose build
docker compose up        # api on 127.0.0.1:${ECHO_PORT:-8000}, user guide at /docs, API reference at /api/docs
docker compose -f compose.test.yml run --rm api-test       # backend tests inside the api image, including `stack` tests against the real runner
docker compose -f compose.test.yml run --rm sandbox-test   # runner tests, including real jails behind the firewall
```

### Web (from `web/`)
```bash
npm ci
npm run dev              # Vite on localhost:5173, proxying /api and /docs to the api on :8000; set ECHO_PUBLIC_URL=http://localhost:5173 for the api and add that address's /api/auth/callback in Entra
npm test                 # vitest: API client, stream parser, markdown rules, tree folding
npm run build            # typecheck, then build to web/dist, which a locally run api serves at / when present
```

### Runner (from `runner/`)
```bash
uv run pytest            # unit tests with a stand-in nsjail; tests marked `jail` only run in the sandbox image
```

## Architecture notes

**Backend layout**: shared plumbing lives in `backend/core/` (the single settings accessor `config.py`, `AppError` and safe messages, error handlers, the response envelope, request ids, logging). Each domain is a folder under `backend/apps/` split into `routers/`, `services/` and `models/` (and `repositories/` for database access). Services stay thin and delegate to small plain-function modules, and pure parsing and mapping live apart from I/O so they can be tested with plain values. Tests under `backend/tests/` are grouped the same way.

**Database**: SQLite at `<data>/echo.db` in the api's data volume (`core/db.py`). Alembic migrations in `backend/migrations/` run at every startup before the api serves, so a deploy never needs a separate migration step. Routes get an `AsyncSession` through the `db` dependency. Write migrations by hand with batch mode in mind, since SQLite cannot alter most columns in place.

**Access**: a router outside `/api/auth` and `/api/health` declares `dependencies=[Depends(current_user)]` (`core/auth.py`), and a route that takes an agent id takes it as `OwnedAgent`, which answers 404 `agent_not_found` unless the signed-in user owns it. Repository reads of owned rows always take the owner id. `check_origin` runs on every request and refuses a POST, PUT, PATCH or DELETE whose `Origin` (or `Referer`) is not `ECHO_PUBLIC_URL`. `tests/accounts/test_access.py` walks every documented route without a session, so a route that forgets the dependency fails there. Provider keys are decrypted only in `credential_service.with_key` and go straight into a provider client; any call to an address a user typed goes through `safe_http.client()`.

**API shape**: every JSON success is `{"success": true, "data": ..., "meta": {"request_id"}}` and every error is `{"success": false, "error": {"code", "message", "details"}, "meta": {"request_id"}}`. Endpoints return their data and the default response class wraps it. Only `AppError` messages reach a caller; anything else becomes a generic message and goes to the log. Streams are not wrapped.

**User guide**: `docs/` holds the end user guide as plain HTML pages served by the api at `/docs` with no build step. It is written for three readers, in this order: people using Echo (`index.html`, `first-agent.html`, `teaching.html`, `chatting.html`, `files.html`, `keys.html`), whoever runs it (`install.html`, `data.html`) and developers (`api.html`); keep setup and `curl` material out of the Using Echo pages. It describes only what is built, never what is planned, and a change that adds or alters something a user sees updates the guide in the same change, including any mock of the app on the page. The look matches the app: `style.css` copies the app's color tokens, `fonts/` holds Inter and JetBrains Mono copied from the web app's `@fontsource` packages, and `guide.js` shares the app's `echo.theme` setting. The page CSP applies here too, so there are no inline scripts, `style` attributes or outside fonts and scripts; behavior goes in `guide.js` and diagrams are HTML and CSS. Guide files are served with `Cache-Control: no-cache` because their names do not change between releases. Each page repeats the same header and sidebar, so a new page is added to every page's sidebar and to `tests/core/test_user_guide.py`, which also follows every link. Pages link to each other relatively, except `404.html`, which uses absolute `/docs/` links because it is served at any missing path. `apps/accounts/routers/auth_router.py` sends a failed sign-in to `first-agent.html`, which explains the error codes.

**Web app**: `backend/core/web_app.py` serves `web/dist` when it exists: `/assets` with long cache headers, and `index.html` for any other path outside `/api`, so client routes load the app. Every non-API response carries a strict Content Security Policy (scripts, fonts, connections only from Echo itself, images only from Echo or `data:`). Agent output is untrusted: `web/src/agent/Markdown.tsx` renders it without raw HTML and never loads remote images, since an injected image address could carry data out. Keep both when changing either. Tests isolate themselves from a local `web/dist` build.

**API docs**: FastAPI's generated docs at `/api/docs` and `/api/openapi.json` are the only API reference. There is no hand-kept collection or committed schema, so every route declares its request and response models and a summary.

**Sandbox**: every command the agent runs and every file operation, including the ones the UI makes (file tree, open, save, git status and diff), goes to the runner, which runs it in that agent's workspace jail. In the api this is `RunnerSandbox` (`backend/sandbox/runner_sandbox.py`), a Strands `PosixShellSandbox` that talks to the runner over a Unix socket on a volume shared only by the two containers. The runner writes each command to a read-only file under `/data/commands/` that is bind mounted into the jail at the same path, because Linux limits one argument to 128 KB and file writes carry their content inside the command. A jail sees only its own workspace (at the same absolute path it has in the sandbox container, so paths mean the same thing everywhere) and its own home at `/home/echo`, read-only system directories, a private `/tmp` and no inherited environment. Its network is the sandbox container's, behind a firewall on uid 1000 that allows DNS and public addresses and rejects loopback, private, metadata and link-local ranges. The two containers are on separate networks and share only the socket volume; the socket is mode 0600 and owned by the api's uid 10001. The firewall is installed by `runner/entrypoint.sh`, which fails the container if any rule fails. The api container has no workspace files: never add a path from the api to a workspace, because a user controls everything in it, including symlinks.

**Agent state**: Strands harness writes conversation sessions and long-term memory from the api process, so they live in the api container's data directory, keyed by agent id (the same id the runner uses for its workspace). Skills are read through the sandbox, so they live in the workspace under `.agent/skills/`, where the agent and the user can both edit them.

**nsjail needs Linux**: namespaces only exist on Linux, so local development and production both run in containers via `compose.yml` (tests via `compose.test.yml`, which includes it), and only the sandbox container is privileged.

## Working with this repo

**Plan before you build.** Before implementing a feature or any non-trivial change, write down the approach and wait for explicit approval before writing code.

**No quick fixes.** Find the root cause and fix it the way it should exist in production, even when that touches more than the line a bug report points at.

**Security is not optional.** For every new endpoint or tool, check tenant isolation (can one user reach another's agent, its workspace, sessions or memory), sandbox escape paths, injection, SSRF and secrets handling before calling it done. Model provider keys stay in the api container and never reach the sandbox container or a jail.

**Keep the changelog current.** Every change adds a line under the current version heading in `CHANGELOG.md` (the newest one, marked "in progress") in the same change. There is no "Unreleased" section. On release, "in progress" becomes the release date, the next version heading opens above it, and `version` in `backend/pyproject.toml` is set to the new number.

**Consistent API shapes.** Before adding an endpoint, check how sibling endpoints shape success and error responses and match them.

**Dependencies.** Prefer what the standard library, the platform or an installed dependency already gives. Pin new dependencies through `uv add` so `uv.lock` records the exact version.

## Writing and documentation style

- No em dashes, anywhere.
- Do not hard-wrap paragraphs inside documents.
- Write in a plain, human style, not AI-assistant-flavored language.
- No emojis in code, comments, commit messages or docs.
- Comment the reasoning behind non-obvious logic. Comments explain the code on their own terms and never reference documents outside this repository.
