import base64
import inspect
import json
from types import SimpleNamespace

import pytest

from apps.chat.services import history
from apps.credentials.services import providers

GEMINI_SIG = base64.b64encode(b"gemini-thought-signature").decode()
ANTHROPIC_SIG = "EqQBCkYIBxgCKkAnthropicSignature=="


def user(text):
    return {"role": "user", "content": [{"text": text}]}


# What a chat can hold after turns on Anthropic, Gemini and OpenAI.
MIXED = [
    user("hi"),
    {"role": "assistant", "content": [
        {"reasoningContent": {"reasoningText": {"text": "hidden-reasoning", "signature": ANTHROPIC_SIG}}},
        {"reasoningContent": {"redactedContent": b"redacted"}},
        {"citationsContent": {"content": [{"text": "Vite 8 "}, {"text": "is out."}], "citations": []}},
    ]},
    user("run it"),
    {"role": "assistant", "content": [
        {"reasoningContent": {"reasoningText": {"text": "hidden-reasoning", "signature": GEMINI_SIG}}},
        {"toolUse": {"toolUseId": "call_1", "name": "shell", "input": {"command": "ls"}, "reasoningSignature": GEMINI_SIG}},
    ]},
    {"role": "user", "content": [{"toolResult": {"toolUseId": "call_1", "status": "success", "content": [{"text": "a.txt"}]}}]},
    {"role": "assistant", "content": [{"reasoningContent": {"reasoningText": {"text": "hidden-reasoning"}}}]},
    user("next"),
]


def test_portable_keeps_only_what_any_provider_takes():
    out = history.portable(MIXED)
    assert out[1]["content"] == [{"text": "Vite 8 is out."}]
    assert out[3]["content"] == [{"toolUse": {"toolUseId": "call_1", "name": "shell", "input": {"command": "ls"}}}]
    assert out[4] == MIXED[4] and out[0] == MIXED[0]
    # A reply that was only reasoning keeps a block, so turns still alternate.
    assert out[5]["content"] == [history.EMPTY_REPLY]
    # The original is untouched.
    assert "reasoningSignature" in MIXED[3]["content"][1]["toolUse"]


@pytest.mark.parametrize("provider, model_id", [
    ("anthropic", "claude-sonnet-5-5"), ("openai", "gpt-6-luna"), ("google", "gemini-3.5-flash"),
])
def test_every_provider_formats_the_portable_history_without_signatures(provider, model_id):
    # The providers' own request formatters, offline. Unchanged, MIXED makes Gemini's raise.
    model = providers.build_model(provider, "k", None, model_id)
    fmt = next(getattr(model, n) for n in ("_format_request_content", "_format_request", "format_request") if hasattr(model, n))
    required = [p for p in inspect.signature(fmt).parameters.values() if p.default is inspect.Parameter.empty]
    request = fmt(history.portable(MIXED), *[None] * (len(required) - 1))
    sent = json.dumps(request, default=lambda o: o.model_dump(exclude_none=True) if hasattr(o, "model_dump") else str(o))
    assert "signature" not in sent and "hidden-reasoning" not in sent


def agent_with(messages, recorded=None):
    state = {} if recorded is None else {history.STATE_KEY: recorded}
    return SimpleNamespace(messages=list(messages), state=SimpleNamespace(get=state.get, set=state.__setitem__), _state=state)


def test_switch_rewrites_only_when_the_model_changes():
    same = agent_with(MIXED, "google/gemini-3.5-flash")
    history.switch_model(same, "google/gemini-3.5-flash")
    assert same.messages == MIXED

    other = agent_with(MIXED, "google/gemini-3.5-flash")
    history.switch_model(other, "anthropic/claude-sonnet-5-5")
    assert other.messages == history.portable(MIXED) and other._state[history.STATE_KEY] == "anthropic/claude-sonnet-5-5"


def test_a_chat_without_a_recorded_model_is_rewritten_and_a_new_one_is_not():
    old = agent_with(MIXED)
    history.switch_model(old, "openai/gpt-6-luna")
    assert old.messages == history.portable(MIXED)

    new = agent_with([])
    history.switch_model(new, "openai/gpt-6-luna")
    assert new.messages == [] and new._state[history.STATE_KEY] == "openai/gpt-6-luna"
