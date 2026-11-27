"""Counts the tokens of every model call a turn makes, and prices each call as it happens.

A turn's models are built for it alone, so the meter patches the instances themselves rather than
wrapping them: the agent, its subagents (which the harness hands the same instance), page summaries
and memory extraction (on the side model) all keep calling the models they were given, and every
call passes through `stream`. Patching the instance keeps the provider's own class, which the
harness inspects. Calls can come from the harness's background thread, so updates take a lock.
"""

import contextvars
import functools
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from strands.models import Model

from apps.usage.services import pricing

KEYS = tuple(pricing.KINDS)
# Set while a summarize call runs: its usage is taken from its result, once, rather than from the
# stream calls the base implementation makes, which a provider's server-side summary does not make.
_summarizing = contextvars.ContextVar("summarizing", default=False)


@dataclass
class Tally:
    tokens: dict[str, int] = field(default_factory=lambda: dict.fromkeys(KEYS, 0))
    calls: int = 0
    # None as soon as one call of the model has no known price.
    cost_micros: int | None = 0


class Meter:
    def __init__(self, provider: str):
        self.provider = provider
        self._lock = threading.Lock()
        self.models: dict[str, Tally] = {}

    def watch(self, model: Model) -> Model:
        """Count every call made through `model` from now on. Returns the same instance. Watching
        it again is a no-op, since the side model can be the turn's own model."""
        if getattr(model, "_echo_meter", None) is self:
            return model
        model._echo_meter = self
        model_id = str((model.get_config() or {}).get("model_id", ""))
        stream, summarize = model.stream, model.summarize

        @functools.wraps(stream)
        async def counted_stream(*args, **kwargs):
            async for chunk in stream(*args, **kwargs):
                # Counted as the chunk passes, so a call that fails after it still counts.
                if not _summarizing.get() and (usage := chunk.get("metadata", {}).get("usage")):
                    self.add(model_id, usage)
                yield chunk

        @functools.wraps(summarize)
        async def counted_summarize(*args, **kwargs):
            token = _summarizing.set(True)
            try:
                result = await summarize(*args, **kwargs)
            finally:
                _summarizing.reset(token)
            if result.usage:
                self.add(model_id, result.usage)
            return result

        model.stream = counted_stream
        model.summarize = counted_summarize
        return model

    def add(self, model_id: str, usage: dict) -> None:
        price = pricing.price_of(self.provider, model_id)
        cost = pricing.cost_micros(price, usage) if price else None
        with self._lock:
            tally = self.models.setdefault(model_id, Tally())
            tally.calls += 1
            for key in KEYS:
                tally.tokens[key] += int(usage.get(key) or 0)
            tally.cost_micros = None if cost is None or tally.cost_micros is None else tally.cost_micros + cost

    def usage(self) -> dict[str, int]:
        """The four token sums over every model, the shape of the done event's usage."""
        with self._lock:
            return {key: sum(t.tokens[key] for t in self.models.values()) for key in KEYS}

    def cost_micros(self) -> int | None:
        """The priced part of the turn's cost, or None when no call had a price."""
        with self._lock:
            priced = [t.cost_micros for t in self.models.values() if t.cost_micros is not None]
            return sum(priced) if priced else None

    def unpriced(self) -> bool:
        with self._lock:
            return any(t.cost_micros is None for t in self.models.values())

    def summary(self) -> dict:
        """What the done event and the turn's record carry: the tokens, the estimated cost in
        millionths of a dollar (None when nothing was priced), and whether some calls had no price."""
        return {**self.usage(), "costMicros": self.cost_micros(), "unpriced": self.unpriced()}

    def rows(self, user_id: str, agent_id: str, chat_id: str, turn_id: str, credential_id: str | None, at: datetime) -> list[dict]:
        """The turn's ledger rows: one per model that was called."""
        with self._lock:
            return [
                {
                    "id": uuid.uuid4().hex, "user_id": user_id, "agent_id": agent_id, "chat_id": chat_id, "turn_id": turn_id,
                    "credential_id": credential_id, "provider": self.provider, "model": model_id,
                    "input_tokens": t.tokens["inputTokens"], "output_tokens": t.tokens["outputTokens"],
                    "cache_read_tokens": t.tokens["cacheReadInputTokens"], "cache_write_tokens": t.tokens["cacheWriteInputTokens"],
                    "calls": t.calls, "cost_micros": t.cost_micros, "at": at,
                }
                for model_id, t in self.models.items() if t.calls
            ]
