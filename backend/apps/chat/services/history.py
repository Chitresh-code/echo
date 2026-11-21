"""Keeps a chat's history usable when its turns move to another provider or model.

Each turn names its own key and model, but the history it resumes keeps blocks only the model that
wrote them can take back: Anthropic's and Gemini's reasoning carry signatures the other provider
rejects, Gemini cannot format redacted reasoning or citation blocks at all, and Gemini signs tool
calls. So when the model changes, those blocks are made portable once, before the turn, and the
session snapshot saves the result."""

import copy

from strands import Agent
from strands.types.content import Messages

# Recorded in the agent's state, which the session snapshot saves with the messages.
STATE_KEY = "echo_model"
# Providers reject an assistant message with no blocks, and dropping it would break the
# user and assistant alternation.
EMPTY_REPLY = {"text": "(reasoning only)"}


def portable(messages: Messages) -> Messages:
    """A copy any provider can take: no reasoning, no tool call signatures, citations as text."""
    result = []
    for message in messages:
        blocks = []
        for block in message["content"]:
            if "reasoningContent" in block:
                continue
            if "citationsContent" in block:
                text = "".join(c.get("text", "") for c in block["citationsContent"].get("content", []))
                blocks.append({"text": text})
                continue
            block = copy.deepcopy(block)
            if "toolUse" in block:
                block["toolUse"].pop("reasoningSignature", None)
            blocks.append(block)
        if not blocks and message["role"] == "assistant":
            blocks = [dict(EMPTY_REPLY)]
        result.append({**message, "content": blocks})
    return result


def switch_model(agent: Agent, model_key: str) -> None:
    """Make the restored history portable when this turn runs on another model than the last one.
    A chat with history but no recorded model predates the record, so its origin is unknown."""
    if agent.messages and agent.state.get(STATE_KEY) != model_key:
        agent.messages[:] = portable(agent.messages)
    agent.state.set(STATE_KEY, model_key)
