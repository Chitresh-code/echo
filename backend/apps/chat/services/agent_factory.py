"""Builds the Strands harness agent for one turn. Everything the agent runs goes through the
workspace's RunnerSandbox, so commands, file tools, skills and web fetches happen in the jail. Only
model calls, session snapshots and memory files stay in the api process."""

from strands import Agent
from strands.models import Model
from strands_harness import create_harness

from core.config import Settings
from core.errors import AppError
from sandbox.runner_sandbox import WORKSPACES_ROOT, RunnerSandbox


# shortcut: a short fixed prompt to get turns working; replace it with tuned instructions per piece of agent behavior.
def instructions(root: str) -> str:
    return f"""You work in a workspace at {root}, which is a git repository. Commands run in an isolated Linux sandbox with that folder as the working directory.
- Read AGENTS.md at the workspace root first if it exists; it holds the user's conventions. Keep it current when you learn something the next session should know.
- Install project dependencies inside the project (a .venv, node_modules). Tools for yourself go in your home folder with pip install --user or npm install -g, which persist between commands.
- The internet is reachable, but localhost and private addresses are not, so you cannot open a server you start. Each command has a time limit, so do not leave servers or watchers running.
- Put reusable workflows and the helper scripts you write for yourself in .agent/skills/<name>/ with a SKILL.md, so later sessions can use them.
- Commit your work with git when a task is done, unless the user asks you not to."""


def check_model(settings: Settings, model: str | None) -> str:
    model = model or settings.default_model
    if model not in settings.models:
        raise AppError(400, "unknown_model", "The model is not one of the models this server offers.")
    return model


def build_agent(settings: Settings, workspace_id: str, chat_id: str, model: str | Model) -> Agent:
    root = f"{WORKSPACES_ROOT}/{workspace_id}"
    return create_harness(
        model=model,
        sandbox=RunnerSandbox(workspace_id, settings.runner_socket, settings.command_timeout),
        session={"id": chat_id, "dir": str(settings.data_dir / "sessions" / workspace_id)},
        memory={"dir": str(settings.data_dir / "memory" / workspace_id)},
        # A path in the sandbox container; the skills plugin reads it through the sandbox.
        skills=[f"{root}/.agent/skills"],
        builtin_tools={
            # curl in the jail, behind its firewall. The "direct" transport would fetch from the api
            # process, which has no address filtering (SSRF).
            "web_fetch": {"transport": "curl"},
            # It runs model-written Python inside the api process, next to the provider keys.
            "programmatic_tool_caller": False,
        },
        instructions=instructions(root),
        callback_handler=None,
    )
