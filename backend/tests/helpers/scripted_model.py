"""A Strands model that plays back fixed replies, so agent turns run in tests without a provider.
Each reply is a list of ("text", str) or ("tool", name, input) parts; one reply is used per model
call, and the last one repeats once the list runs out."""

import json
from typing import Any

from strands.models import Model


class ScriptedModel(Model):
    def __init__(self, replies: list[list[tuple]]):
        self.replies = replies
        self.calls = 0
        # How many messages the model was given on each call, to check a session resumed.
        self.message_counts: list[int] = []
        self.first_messages: list | None = None
        self.config: dict[str, Any] = {"model_id": "scripted"}

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> Any:
        return self.config

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        self.message_counts.append(len(messages))
        if self.first_messages is None:
            self.first_messages = messages
        yield {"messageStart": {"role": "assistant"}}
        uses_tool = False
        for i, part in enumerate(reply):
            if part[0] == "text":
                yield {"contentBlockStart": {"start": {}}}
                yield {"contentBlockDelta": {"delta": {"text": part[1]}}}
            else:
                uses_tool = True
                yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{self.calls}-{i}", "name": part[1]}}}}
                yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(part[2])}}}}
            yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use" if uses_tool else "end_turn"}}
