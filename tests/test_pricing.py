"""Pricing-table resolution for cost reporting (no network / no client)."""

from eval.frontier import PRICING_USD_PER_MTOK


def _match(model: str):
    """Mirror FrontierCEO.estimate_cost_usd's substring match."""
    m = model.lower()
    for key, rate in PRICING_USD_PER_MTOK.items():
        if key in m:
            return rate
    return None


def test_qwen_ids_resolve_to_distinct_rates():
    plus = _match("Qwen-Ambassador/Qwen3.7-Plus")
    mx = _match("Qwen-Ambassador/Qwen3.7-Max")
    assert plus == (0.32, 1.28)
    assert mx == (2.50, 7.50)
    assert plus != mx  # no cross-matching between Plus and Max


def test_claude_and_openai_ids_still_resolve():
    assert _match("Claude-Opus-4") == (15.00, 75.00)
    assert _match("Claude-Sonnet-4") == (3.00, 15.00)
    assert _match("gpt-4o") == (2.50, 10.00)
    assert _match("gpt-4o-mini") == (0.15, 0.60)  # more-specific key wins


def test_cost_estimate_math():
    # 1M input + 1M output at Qwen3.7-Plus rates = 0.32 + 1.28 = 1.60
    rate = _match("qwen3.7-plus")
    cost = 1_000_000 / 1e6 * rate[0] + 1_000_000 / 1e6 * rate[1]
    assert abs(cost - 1.60) < 1e-9


def test_unknown_model_has_no_price():
    assert _match("some-unlisted-model") is None
