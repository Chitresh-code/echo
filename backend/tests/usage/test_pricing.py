from apps.usage.services import pricing
from apps.usage.services.pricing import Price, cost_micros, price_of


def test_lookup_per_provider():
    assert price_of("anthropic", "claude-opus-5-5") is not None
    assert price_of("openai", "gpt-6-luna") is not None
    # Gemini entries are listed under a gemini/ prefix.
    assert price_of("google", "gemini-3.5-flash-lite") is not None
    assert price_of("anthropic", "no-such-model") is None
    # A custom endpoint's prices are its own, never guessed from a model name.
    assert price_of("openai_compatible", "gpt-6-luna") is None


def test_a_plain_call():
    price = Price(((0, {"input_cost_per_token": 3e-6, "output_cost_per_token": 15e-6, "cache_read_input_token_cost": 3e-7, "cache_creation_input_token_cost": 3.75e-6}),))
    usage = {"inputTokens": 1000, "outputTokens": 200, "cacheReadInputTokens": 10_000, "cacheWriteInputTokens": 2000}
    # 0.003 + 0.003 + 0.003 + 0.0075
    assert cost_micros(price, usage) == 16_500


def test_long_context_tier_applies_to_the_whole_call():
    price = price_of("anthropic", "claude-haiku-5-5")
    small = cost_micros(price, {"inputTokens": 100_000, "outputTokens": 0})
    big = cost_micros(price, {"inputTokens": 100_001, "outputTokens": 0})
    assert small == 10_000
    # Above 100k the input rate is five times higher, for every token of the call.
    assert big == round(100_001 * 5e-7 * 1_000_000)
    # Cached tokens count toward the prompt size.
    assert cost_micros(price, {"inputTokens": 1, "cacheReadInputTokens": 100_000}) > cost_micros(price, {"inputTokens": 1, "cacheReadInputTokens": 99_999}) * 4


def test_missing_cache_rates_bill_at_the_input_rate():
    price = Price(((0, {"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6}),))
    assert cost_micros(price, {"cacheReadInputTokens": 1000, "cacheWriteInputTokens": 1000}) == 2000


def test_rounds_to_micros_and_names_its_source():
    price = Price(((0, {"input_cost_per_token": 1e-7, "output_cost_per_token": 1e-7}),))
    assert cost_micros(price, {"inputTokens": 4}) == 0
    assert cost_micros(price, {"inputTokens": 6}) == 1
    assert pricing.source()["source"].startswith("https://github.com/BerriAI/litellm/blob/")
