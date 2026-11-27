import asyncio
import threading
from types import SimpleNamespace

import pytest

from apps.usage.services import pricing
from apps.usage.services.meter import Meter
from tests.helpers.scripted_model import ScriptedModel

USAGE = {"inputTokens": 1000, "outputTokens": 100, "cacheReadInputTokens": 0, "cacheWriteInputTokens": 0}


def haiku(usage=USAGE):
    model = ScriptedModel([[("text", "hi")]], usage=usage)
    model.config["model_id"] = "claude-haiku-5-5"
    return model


async def drain(model):
    return [chunk async for chunk in model.stream([{"role": "user", "content": [{"text": "hi"}]}])]


def test_counts_and_prices_each_call_and_passes_chunks_through():
    meter, model = Meter("anthropic"), haiku()
    plain = asyncio.run(drain(haiku()))
    assert meter.watch(model) is model and meter.watch(model) is model  # watching twice counts once
    assert asyncio.run(drain(model)) == plain
    asyncio.run(drain(model))
    one = pricing.cost_micros(pricing.price_of("anthropic", "claude-haiku-5-5"), USAGE)
    assert meter.summary() == {"inputTokens": 2000, "outputTokens": 200, "cacheReadInputTokens": 0, "cacheWriteInputTokens": 0, "costMicros": 2 * one, "unpriced": False}
    [row] = meter.rows("u", "a", "c", "t", "k", None)
    assert row["calls"] == 2 and row["model"] == "claude-haiku-5-5" and row["cost_micros"] == 2 * one and row["credential_id"] == "k"


def test_a_call_that_fails_after_its_usage_still_counts():
    model = haiku()
    real = model.stream

    async def breaks(*args, **kwargs):
        async for chunk in real(*args, **kwargs):
            yield chunk
        raise RuntimeError("connection reset")

    model.stream = breaks
    meter = Meter("anthropic")
    meter.watch(model)
    with pytest.raises(RuntimeError):
        asyncio.run(drain(model))
    assert meter.usage()["inputTokens"] == 1000


def test_summarize_is_counted_once_from_its_result():
    model, meter = haiku(), Meter("anthropic")

    async def summarize(*args, **kwargs):
        await drain(model)  # the base implementation streams; that call must not count twice
        return SimpleNamespace(usage={"inputTokens": 7, "outputTokens": 3})

    model.summarize = summarize
    meter.watch(model)
    asyncio.run(model.summarize([]))
    assert meter.usage()["inputTokens"] == 7 and meter.rows("u", "a", "c", "t", None, None)[0]["calls"] == 1


def test_an_unpriced_model_has_tokens_but_no_cost():
    meter = Meter("openai_compatible")
    meter.add("my-local-llama", USAGE)
    assert meter.summary()["costMicros"] is None and meter.summary()["unpriced"] is True
    meter = Meter("anthropic")
    meter.add("claude-haiku-5-5", USAGE)
    meter.add("claude-from-the-future", USAGE)
    # The total keeps what was priced and says something is left out.
    assert meter.cost_micros() > 0 and meter.unpriced() is True


def test_calls_from_many_threads_all_count():
    meter = Meter("anthropic")
    threads = [threading.Thread(target=lambda: [meter.add("claude-haiku-5-5", {"inputTokens": 1}) for _ in range(500)]) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert meter.usage()["inputTokens"] == 4000
