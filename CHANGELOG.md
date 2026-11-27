# Changelog

All notable changes to Echo are recorded here. The format follows Keep a Changelog, and versions follow semantic versioning (0.x until the first public release).

## Keeping this up to date

Every change adds a line under the current version heading (the newest one, marked "in progress") in the same change, in the group that fits: Added, Changed, Fixed, Removed or Security. Write it for someone running Echo, not as a commit message.

Until the first public release the major version stays 0. Each feature gets its own minor version (0.6.0, 0.7.0), and a fix shipped on its own between features gets the next patch version (0.6.1). When a version is finished, replace "in progress" with the date, set `version` in `backend/pyproject.toml` and `web/package.json` to it, and open the next heading above it marked "in progress" when work on the next one starts.

## 0.12.0 (2026-11-27)

Slash commands in the message box.

### Added

- Commands in the message box: type `/` at the start of a line for a menu of commands, then the command name and a space for its choices. `/model` lists the models of every key, grouped by key, and `/effort` sets how hard the model thinks. Up and Down move, Enter or Tab picks, Escape closes the menu and keeps the text, and typing narrows the list. A message that is only a known command is never sent, while an unknown `/word` (a path such as `/etc/hosts`) is sent as ordinary text. The menu works with a keyboard alone and is read out by screen readers.
- The model and effort the next message uses show as a small label in the corner of the message box (the effort only when it is not auto). Clicking it opens the same choices with a search field, for touch screens and anyone who does not use `/`.
- A key whose models fail to load says why in the menu and can be retried on its own. Models are listed only once a menu first needs them.

### Changed

- The model and effort dropdowns under the message box are gone; use `/model`, `/effort` or the label. The message box hints at `/` in its placeholder, and a send without a model says "Choose a model with /model first."

### Fixed

- A key for an OpenAI-compatible service is only offered effort auto, and a higher effort remembered from another key is sent as auto, so its turns are no longer refused.

## 0.11.0 (2026-11-27)

Chat-first app shell.

### Added

- A workspace can be created without a name (`POST /api/agents` with `{}`). It is called "New workspace" until its first message, which names it at once from the start of the message and then by a short title the model writes, sent to the chat as a `title` event. A name the user sets first always wins. A title that fails or takes longer than 15 seconds leaves the first name and never fails the turn; the stream can stay open up to that long after `done` to deliver it.

- A sidebar on every signed-in page: New workspace, Credentials, the recent workspaces with Rename and Delete, and the account menu with the theme switch. It collapses to a rail on wide screens, remembered in the browser, and opens as a drawer on narrow ones.
- A rich text message box (Tiptap): bold, italic, code, code blocks, lists, quotes and links by Markdown shortcuts or Cmd/Ctrl with B, I and E, sent as Markdown. Only addresses typed with http, https, mailto or www become links by themselves, so a file name such as hello.py stays text. Enter sends; Shift+Enter starts a new paragraph or list item; inside a code block Enter adds a line and Cmd/Ctrl+Enter sends; Enter while an input method is composing never sends. Pasted Markdown becomes formatting and pasted web pages keep only that formatting. Unsent text is kept per workspace in the browser tab, a refused send puts the message back, and a counter shows near the 100,000 character limit.
- The home page is a message box: each message starts a new workspace (no name or job to fill in) and opens it with the message. A refused start, such as the workspace limit, says why and keeps the message; with no model key the box is off and links to Credentials.
- A new workspace page around the chat. The header shows the workspace's name, which updates live as the first message names it and again when the title arrives, and which can be renamed by clicking it; a count of changed files; New chat; a button for the files panel; and a menu with Rename, Name and purpose, and Delete. The browser tab shows the name too. Your own messages show their Markdown formatting.
- The files panel (files, skills, notes, editor and preview) opens beside the chat, remembered in the browser, and can be resized by dragging or with the arrow keys from 320 pixels to 60% of the window. It opens by itself when the chat links to a file or a learned skill, and keeps unsaved edits while hidden. On a narrow screen it covers the chat.
- Leaving a workspace while its agent is working asks first: Stay keeps the turn running, Leave and stop stops it. Closing or reloading the tab warns too. Signing out never asks.

### Changed

- Workspaces open at `/w/<id>`; old `/agents/<id>` links redirect there. The Agents page and the top bar are gone, since the sidebar is the list.
- The message from home is sent exactly once: a reload or Back never sends it again, and if it cannot be sent it stays in the box. A turn refused before it starts puts the message back; a connection lost mid-turn says the turn stopped and that what the agent already changed stays in its files.
- Chat errors show the message and the request id only, no longer the error code.
- When model keys fail to load, the model picker says so with Retry, instead of asking to add a key.
- Renaming from a menu keeps the name field open; before, the menu took focus back and ended the rename at once. Closing those menus returns focus to their button.
- Signing out clears unsent message drafts kept in the browser tab, including text typed just before signing out.
- Each user may now have 50 workspaces by default instead of 10 (`ECHO_MAX_AGENTS`), since every message from the home screen starts one. With the default 2 GB per workspace, size the disk for up to 100 GB per person, or lower either setting.
- Errors about a workspace's limit, a turn in progress and a missing workspace say "workspace" instead of "agent". The error codes are unchanged.
- The user guide describes the home screen, the sidebar and the workspace page: "Your first agent" is now "Your first workspace" (same address), and Chatting covers formatting, unsent messages and leaving during a reply.
- The sign-in page, agent pages, user guide and README describe Echo as a self-improving agent harness, and an agent's "Job" is now called its purpose. The API field is still `job`.

## 0.10.0 (2026-11-27)

Agent networks and live preview.

### Added

- The runner keeps long-running processes per workspace: `POST /workspaces/{id}/processes` starts a named command (a dev server, a watcher) that outlives the request, `GET` lists them with the ports listening in the workspace, `GET .../{name}/logs` returns the end of its log and `DELETE .../{name}` stops it. Each is a jail with the usual limits and a 2 hour time limit (`RUNNER_PROCESS_TIMEOUT`), at most 3 per workspace and 20 per sandbox (`RUNNER_MAX_PROCESSES_PER_WORKSPACE`, `RUNNER_MAX_PROCESSES`). Logs are kept to about 1 MB under `/data/processes`. Deleting a workspace stops its processes.
- The runner forwards HTTP to a server in a workspace: `/workspaces/{id}/ports/{port}/http/{path}` passes the request (any method, headers, body) to that port on the workspace's own loopback, IPv4 or IPv6, and streams the response back. It answers 404 `no_network` when nothing has run in the workspace and 502 `upstream_unreachable` when nothing listens on the port. It only ever reaches the named workspace's loopback. WebSocket upgrades are not forwarded.
- The agent has a `process` tool to start, stop, list and read the logs of dev servers and watchers in its workspace. Starting one waits two seconds and returns its first log lines and the listening ports, so a crash or a wrong port shows at once. Subagents have it too, and the chat shows the process name on its tool row.
- `GET /api/agents/{id}/processes`, `GET /api/agents/{id}/processes/{name}/logs` and `DELETE /api/agents/{id}/processes/{name}` list an agent's processes and listening ports, show a process's output and stop it.
- Previews of the agents' dev servers, turned on with `ECHO_PREVIEW_URL` (for example `http://preview.localhost:8000`). `POST /api/agents/{id}/preview` with a port returns a link to `<agent>-<port>.<preview domain>`, good for one minute, which signs the browser in to that one preview with an `echo_preview` cookie (HttpOnly, Secure, SameSite=None, Partitioned, 8 hours) and then shows the server's pages. A preview host only ever serves the preview: it never reaches the api or the app, the cookie is never passed to the agent's server, a server's own `echo_preview` cookie is dropped, the server sees `Host: localhost:<port>`, only Echo may frame it, and request bodies are capped at 10 MB. Each request checks the agent still belongs to the user. WebSockets are refused on preview hosts.
- A Preview view next to the editor on the agent page. It lists the agent's processes with their state, shows a process's output, stops a running one, and lists the ports listening in the workspace. Clicking a port shows its page in a sandboxed frame, with reload and open in a new tab. When previews are not set up, it says so. When nothing answers on a port, or nothing has run yet, the preview shows a short page instead of the runner's JSON error.

### Changed

- Each agent's commands now run in a network of their own. A server started in a command answers on `localhost` to the rest of that command, and no other agent can reach it. The internet is reached as before, with the same addresses refused, and names are looked up through a resolver in the sandbox container.
- The sandbox image adds `iproute2` and `dnsmasq-base`.
- The agent is told it can use localhost within its workspace, to start servers with the `process` tool instead of `&` or `nohup`, and to tell the user which port to open.
- The app's Content-Security-Policy allows frames from the preview domain, and from nothing when previews are off.
- The user guide covers servers and previews (Chatting), turning previews on (Install), the process and preview endpoints (API) and what the sandbox volume now holds (Data).

### Security

- A preview's `Set-Cookie` headers lose their `Domain` attribute, so a page an agent wrote cannot set cookies on other preview hosts or on a parent domain it shares with Echo.

## 0.9.0 (2026-11-22)

Delegated work in chat.

### Added
- The agent can hand a self-contained part of a task to a subagent, with the same tools and workspace. Each one shows in the chat as a block with its task, its tool calls and whether it finished. Up to two run at once per reply, a subagent cannot start its own, and their tokens count in the reply's total.
- For multi-step tasks the agent keeps a plan, shown as a checklist that updates as it works.
- Tool rows show what each call acted on (the command, file, address or skill) and are marked when the call failed. The turn stream has new `tool_detail`, `tool_result`, `todos` and `delegate*` events.

### Changed
- The agent can no longer run a tool other than `subagent` in the background, where its result would be replaced by a "dispatched" note.

### Fixed
- The guide and the chat said Stop only stops watching a reply. It stops the reply and its running command.

## 0.8.0 (2026-11-22)

Quotas, so one user cannot take over the sandbox host.

### Added
- Agents can be deleted, with the bin next to each agent on the Agents page or `DELETE /api/agents/{id}`. It removes the agent's files, home, skills, notes and chats for good, and is refused with `agent_busy` while one of its chats is answering.
- Each agent may use 2 GB for its files and home (`ECHO_AGENT_DISK_MB`). The runner measures after each command; over the limit the agent can still read and delete but not write, and is told so on its next command. Saving from the editor answers `disk_quota_exceeded`. The Files tab shows how much the agent uses, and `GET /api/agents/{id}/usage` returns it.
- Each user may have 10 agents (`ECHO_MAX_AGENTS`, `agent_limit_reached`) and 2 replies running at once across their chats (`ECHO_MAX_RUNNING_TURNS`, 429 `too_many_turns`).

### Changed
- The stack tests delete the agents and workspaces they create.

## 0.7.1 (2026-11-22)

### Fixed
- Prompt caching now applies to OpenAI keys as well as Anthropic ones: each chat sends its own cache key, so long chats reread less at full price. Google caches on its own and is unchanged.

## 0.7.0 (2026-11-22)

A redesigned user guide, written for the people who use Echo.

### Changed
- The user guide at `/docs` is reorganized by reader: Using Echo (Welcome, Your first agent, Teaching your agent, Chatting, Files and changes, Model keys), Running Echo (Install and set up, Data and backups) and Developers (Using the API, with every `curl` example). Pages that used to mix setup and API detail into everyday use no longer do.
- The guide now looks like the app: its colors, fonts and logo, dark and light themes that follow the app's theme choice, diagrams of how an agent learns and how its workspace is shut off, and pictures of the chat, Skills and Notes tabs. Code blocks have a copy button, and long pages list their sections.
- A failed sign-in now lands on `/docs/first-agent.html`, which explains the error, instead of `/docs/signing-in.html`.
- Guide files are sent with `Cache-Control: no-cache`, so a browser never shows a new page with an old stylesheet after an upgrade.
- Data and backups adds how to restore the two volumes, and that the secret key must be kept with a backup.

### Removed
- The guide pages `getting-started.html`, `signing-in.html`, `agents.html` and `chat.html`. Their content moved to the new pages; the old addresses show the guide's not-found page, which links home.

## 0.6.1 (2026-11-22)

### Fixed
- Opening `/docs` without a trailing slash showed the browser app instead of the user guide. It now redirects to `/docs/`.

## 0.6.0 (2026-11-22)

Workflow learning: the agent knows its job, saves what it learns as skills, and the app shows its skills and notes.

### Added
- The agent's skills and notes: `GET /api/agents/{id}/skills` lists its skills with their description and whether the harness loads them (`ok`, `warning` or `skipped`, with the reason), `GET /api/agents/{id}/notes` lists what it remembers, newest first, and `DELETE /api/agents/{id}/notes/{name}` makes it forget one. A missing note answers 404 `note_not_found`.
- The agent page has Files, Skills and Notes tabs. Skills open in the editor; notes can be forgotten.
- The chat shows learning: the `done` event lists the skills the turn added, changed or removed as `learned`, worked out from the skill files on disk, and the chat shows them as a "Learned" line that opens each skill. A `skill` event names the skill a `skills` tool call loaded, and its tool row says so.
- Evals: a `learns` task that corrects the agent in one chat and checks a new chat follows the correction and that a skill was saved. A task can send prompts in a second, new chat (`next_chat`), and checks get the agent's loaded skills.
- A README with what Echo is, how to run it and where its data lives, and a "Where your data is kept" section in the getting started guide with how to back up the volumes.

### Changed
- The agent's instructions now carry the agent's name and job, read at every turn, so a rename or a new job applies from the next message. They frame the agent as learning that one job: use its skills first, save corrections as skills in `.agent/skills/` with the exact `SKILL.md` front matter, say in one line what it learned, and say when a request falls outside its job. Without a job, it asks you to describe one.
- A skill the harness cannot load, or that breaks the format, is named in the agent's instructions on the next turn so it fixes it.
- The test services moved from the `test` profile in `compose.yml` to `compose.test.yml`, which includes it: run them with `docker compose -f compose.test.yml run --rm api-test` (or `sandbox-test`).

## 0.5.0 (2026-11-21)

Agents and the browser app.

### Added
- Agents have a name and the job they learn: `POST /api/agents` takes `name` (1 to 80 characters) and `job` (up to 500), `GET /api/agents/{id}` returns one agent, `PATCH /api/agents/{id}` renames it or changes its job, and the list shows when each agent was last used, most recently used first.
- The browser app (`web/`, React, MUI and a bundled Monaco editor), in dark and light themes that follow the system with a toggle: sign in with Microsoft; your agents with their name, job and when you last used them, with search, New agent and editing an agent; Credentials to add, list and delete model keys and see each key's models; and an agent's page with the file explorer and git status, an editor that saves with Ctrl or Cmd+S, a diff of each changed file against the last commit, and the chat with a key, model and effort picker, the reply as it streams, a row per tool, and the turn's tokens and time. Panels stack on a narrow window. The chat continues after a reload but does not show earlier messages, since chats are not stored.
- User guide: `agents.html` (was `workspaces.html`) describes agents and their page, `chat.html` the chat panel, `keys.html` the Credentials page and keys with their own model list, and every page says agent.
- The api serves the browser app at `/` from the same address as the API, built into the api image. Any page path that is not under `/api` or `/docs` loads the app.
- OpenAI-compatible keys can carry their own model list (`models` when adding the key), for endpoints that serve chat but no `/models`. Such a key is checked with one short chat request to the first model instead of listing models, and `GET /api/credentials/{id}/models` returns the list you gave. A model the endpoint does not serve answers 400 `model_not_available`; a model list on another provider answers 400 `models_not_supported`.

### Changed
- What a user creates is now an agent, not a workspace. Every route moved: `/api/workspaces` is `/api/agents`, and `/api/workspaces/{workspace_id}/...` (tree, file, git, chats and turns) is `/api/agents/{agent_id}/...`. `POST /api/agents` needs a `name`. The error codes `workspace_not_found` and `invalid_workspace_id` are now `agent_not_found` and `invalid_agent_id`. Existing workspaces become agents named "Untitled agent" at the first start, with their files, chats and memory kept.

### Fixed
- Times in API responses (`created_at`, `last_used_at`) now carry their UTC offset. They came back from the database without one, so a browser read them as local time.

### Security
- Pages outside `/api` (the browser app and the user guide) carry a Content Security Policy that allows scripts, styles, fonts and connections only from Echo itself and images only from Echo or `data:` URLs, and cannot be framed by another site; they also send `X-Content-Type-Options: nosniff` and `Referrer-Policy: same-origin`.

## 0.4.0 (2026-11-21)

The agent's tools and instructions, with evals.

### Added
- The `done` event carries the turn's token use on the chosen model (`usage`: input, output, cache read and cache write tokens).
- Evals in `backend/evals/`: five real tasks run by hand through the API on your own key, with a token cap, for tuning the agent's tools and instructions. They are never run by the test suite.
- `ECHO_COMMAND_TIMEOUT_MAX` (default 1800), the longest a single command may run; keep it equal to the sandbox's `RUNNER_TIMEOUT_MAX`. Startup fails when `ECHO_COMMAND_TIMEOUT` is above it.

### Changed
- The agent's instructions are rewritten: who Echo is, the sandbox's real limits, treating web pages, files and command output as data rather than instructions, git habits, and ending each turn with what changed, how it was checked and what was not done.
- Page summaries from web fetches and memory extraction after each turn run on the provider's small model (Claude Haiku 5.5, gpt-6-luna or Gemini 3.5 Flash Lite) with reasoning off, on the same key, instead of on the turn's model and effort. OpenAI-compatible keys still use the turn's model.

### Removed
- The agent's `subagent` tool, which ran a whole child agent on your key with nothing of it shown in the chat stream.

### Fixed
- The agent's commands now use `ECHO_COMMAND_TIMEOUT` as their default time limit. Before, the shell tool always sent its own 2 minute default, and the agent was not told it could ask for longer.

## 0.3.1 (2026-11-21)

### Fixed
- Moving a chat to another provider or model could fail the next turn, because the chat kept the earlier model's signed reasoning and citation blocks that the new provider rejects. Echo now records each chat's model and, when it changes, keeps the conversation but drops the earlier hidden reasoning.

## 0.3.0 (2026-11-21)

Reasoning effort per turn.

### Added
- A turn can choose how hard the model reasons: `effort` in the turn's body (`auto`, `off`, `minimal`, `low`, `medium`, `high`, `xhigh` or `max`, default `auto`, the level recommended for the model). A level the model does not take answers 400 `effort_not_supported` before the turn starts, naming the levels it does take. OpenAI-compatible keys take only `auto`.

## 0.2.1 (2026-11-21)

### Fixed
- Tools that use WebAssembly on Node 22, such as a Vite build, failed in jails with a WebAssembly memory error. Jails no longer cap address space; `RUNNER_JAIL_MEMORY_MB` (default 4096) now limits the memory a jail actually uses.

### Security
- Each jail runs in its own cgroup with a memory limit (`RUNNER_JAIL_MEMORY_MB`, no swap) and at most 1024 processes, so one workspace cannot use up the host's memory or fork without limit. A jail that goes over its memory has its largest process killed. The sandbox needs cgroup v2 with the memory and pids controllers, and refuses to start without them.

## 0.2.0 (2026-11-21)

Accounts and users' own model keys.

### Added
- The api keeps its own records in an SQLite database, `echo.db` in its data volume, and applies database migrations itself at startup.
- New required settings for accounts: `ECHO_PUBLIC_URL`, `ECHO_MS_TENANT_ID`, `ECHO_MS_CLIENT_ID`, `ECHO_MS_CLIENT_SECRET` and `ECHO_SECRET_KEY`. Startup fails when one is missing or malformed, without printing the secret values.
- Sign in with Microsoft: `GET /api/auth/login` signs in through your organization's Entra tenant and returns to the API reference with a session; `GET /api/auth/me` shows who is signed in and `POST /api/auth/logout` ends the session. Only accounts in the configured tenant are accepted, and a person is recognised by their Entra account, never by email. Sessions last 7 days.
- Workspaces belong to the user who created them: the list shows only your own, and someone else's workspace answers 404 `workspace_not_found`, the same as one that does not exist. Every workspace and chat route needs a signed-in user (401 `not_signed_in`).
- Your own model provider keys: `POST /api/credentials` adds an Anthropic, OpenAI, Google (AI Studio) or OpenAI-compatible key, `GET /api/credentials` lists them, `DELETE /api/credentials/{id}` removes one and `GET /api/credentials/{id}/models` lists the models it can use. A key is checked with the provider before it is stored, and only its last four characters are ever shown. A refused key answers `invalid_key`; other provider failures answer `provider_error` without the provider's text.
- A turn names the key and model it runs on: `credential_id` and `model` in the turn's body. A missing or someone else's key answers 404 `credential_not_found` before the turn starts.
- User guide: getting started covers registering Echo in Microsoft Entra, and new pages cover signing in (and using the session from `curl`) and keys (adding your own provider key). A failed sign-in lands on the signing in page with its error code.

### Removed
- The server-wide model list and provider keys: `ECHO_MODELS`, `ANTHROPIC_API_KEY` and the like are not read, `GET /api/models` is gone, and startup logs a warning when `ECHO_MODELS` is still set. The LiteLLM provider is no longer installed; models come from each user's own keys through the Anthropic, OpenAI and Gemini providers.

### Security
- A POST, PUT, PATCH or DELETE whose `Origin` (or `Referer`) is not `ECHO_PUBLIC_URL` is refused with 403 `bad_origin`, so another site's page cannot act with a signed-in user's cookie. Open Echo at exactly that address. Clients like `curl` that send neither header are not affected.
- Sign-in uses the authorization code flow with PKCE, and the ID token's signature, audience, expiry, nonce, issuer and tenant are all checked. The session cookie is HttpOnly, SameSite=Lax and Secure when Echo is served over https; the database keeps only a hash of it. A failed sign-in tells the browser only an error code.
- Provider keys are stored encrypted with `ECHO_SECRET_KEY` and never returned. Changing that key makes stored keys unreadable (`credential_unreadable`), so they must be added again.
- A custom endpoint must be https, with no user name in the address. Echo resolves its host when connecting and refuses loopback, private, link-local (cloud metadata), carrier-grade NAT, multicast and reserved addresses (`endpoint_not_allowed`), then connects to the address it checked. It ignores proxy settings and follows no redirects.

## 0.1.0 (2026-11-21)

The sandboxed agent core.

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
