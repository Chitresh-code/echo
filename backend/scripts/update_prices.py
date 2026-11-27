"""Refresh apps/usage/prices.json from LiteLLM's public model price list (MIT licensed).

Run before a release:  uv run python scripts/update_prices.py [git-ref]

Keeps the chat models of the providers Echo supports, and of each only the per-token rates Echo
prices with: input, output, cache read and cache write, plus their long-context tiers. Batch, flex,
priority and 1 hour cache rates are dropped because Echo never sends requests on those tiers. The
diff of the result is what a reviewer checks.
"""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO = "BerriAI/litellm"
FILE = "model_prices_and_context_window.json"
PROVIDERS = {"anthropic", "openai", "gemini"}
MODES = {"chat", "responses"}
RATE = re.compile(r"^(input_cost_per_token|output_cost_per_token|cache_read_input_token_cost|cache_creation_input_token_cost)(_above_\d+k_tokens)?$")
OUT = Path(__file__).resolve().parent.parent / "apps" / "usage" / "prices.json"


def main(ref: str = "main") -> None:
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        commit = client.get(f"https://api.github.com/repos/{REPO}/commits/{ref}", headers={"Accept": "application/vnd.github.sha"}).raise_for_status().text.strip()
        data = client.get(f"https://raw.githubusercontent.com/{REPO}/{commit}/{FILE}").raise_for_status().json()
    models = {}
    for name, entry in sorted(data.items()):
        if not isinstance(entry, dict) or entry.get("litellm_provider") not in PROVIDERS or entry.get("mode") not in MODES:
            continue
        rates = {key: value for key, value in entry.items() if RATE.match(key) and isinstance(value, int | float)}
        if "input_cost_per_token" in rates and "output_cost_per_token" in rates:
            models[name] = rates
    document = {
        "source": f"https://github.com/{REPO}/blob/{commit}/{FILE}",
        "fetched": datetime.now(UTC).date().isoformat(),
        "models": models,
    }
    OUT.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n")
    print(f"{len(models)} models written to {OUT}")


if __name__ == "__main__":
    main(*sys.argv[1:2])
