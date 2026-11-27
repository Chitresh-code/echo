"""Turning a model call's token counts into an estimated cost.

Prices are list prices from prices.json (refreshed by scripts/update_prices.py), so every cost is an
estimate: discounts, free tiers and taxes are not in it. Money is kept in millionths of a dollar
(micros) as integers, so sums are exact however many calls are added up.
"""

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PRICES = Path(__file__).resolve().parent.parent / "prices.json"
KINDS = {
    "inputTokens": "input_cost_per_token",
    "outputTokens": "output_cost_per_token",
    "cacheReadInputTokens": "cache_read_input_token_cost",
    "cacheWriteInputTokens": "cache_creation_input_token_cost",
}
_TIER = re.compile(r"_above_(\d+)k_tokens$")


@dataclass(frozen=True)
class Price:
    # Rates in dollars per token, from the lowest tier up: (threshold in prompt tokens, rates).
    tiers: tuple[tuple[int, dict[str, float]], ...]


@cache
def _table() -> dict:
    return json.loads(PRICES.read_text())


def source() -> dict[str, str]:
    """Where the prices came from and when, for the UI's estimate note."""
    return {"source": _table()["source"], "fetched": _table()["fetched"]}


# shortcut: list prices from the shipped file only, no batch, regional or negotiated rates; add a per-key override if users need exact numbers.
def price_of(provider: str, model: str) -> Price | None:
    """The list price of `model` on `provider`, or None when it is unknown. An openai_compatible
    endpoint serves whatever it likes at its own prices, so it is never guessed."""
    names = {"anthropic": [model], "openai": [model], "google": [f"gemini/{model}", model]}.get(provider, [])
    rates = next((_table()["models"][n] for n in names if n in _table()["models"]), None)
    if rates is None:
        return None
    tiers: dict[int, dict[str, float]] = {0: {}}
    for key, rate in rates.items():
        match = _TIER.search(key)
        threshold = int(match.group(1)) * 1000 if match else 0
        tiers.setdefault(threshold, {})[key[: match.start()] if match else key] = rate
    # A tier lists only the rates that change; the rest carry over from the base.
    base = tiers[0]
    return Price(tuple((t, base | tiers[t]) for t in sorted(tiers)))


def cost_micros(price: Price, usage: dict) -> int:
    """The cost of one call. Long-context tiers apply per call, by the size of its prompt (input
    plus cached tokens), which is how providers bill them. A missing cache rate is billed at the
    input rate."""
    prompt = usage.get("inputTokens", 0) + usage.get("cacheReadInputTokens", 0) + usage.get("cacheWriteInputTokens", 0)
    rates = next(r for t, r in reversed(price.tiers) if prompt > t or t == 0)
    dollars = sum(usage.get(kind, 0) * rates.get(key, rates["input_cost_per_token"]) for kind, key in KINDS.items())
    return round(dollars * 1_000_000)
