"""Cost estimates only appear when unit prices are configured for the endpoint.

The prices used to be hard-coded DeepSeek rates, so pointing --base-url at any
other provider produced a confidently wrong number in the report and the UI.
"""

import pytest

from core.pricing import (
    TokenPricing,
    build_pricing,
    format_cost_usd,
    normalize_endpoint,
)
from core.translator import TokenStats


class TestCostCalculation:
    def test_cost_uses_configured_rates(self):
        pricing = TokenPricing(input_per_m=2.0, output_per_m=8.0, cached_per_m=0.5)

        cost = pricing.cost_usd(
            input_tokens=1_000_000, output_tokens=500_000, cached_tokens=0
        )

        assert cost == pytest.approx(2.0 + 4.0)

    def test_cached_tokens_are_billed_at_the_cached_rate(self):
        pricing = TokenPricing(input_per_m=2.0, output_per_m=8.0, cached_per_m=0.5)

        cost = pricing.cost_usd(
            input_tokens=1_000_000, output_tokens=0, cached_tokens=400_000
        )

        # 600k uncached at 2.0 + 400k cached at 0.5
        assert cost == pytest.approx(1.2 + 0.2)

    def test_zero_usage_costs_nothing(self):
        pricing = TokenPricing(input_per_m=2.0, output_per_m=8.0, cached_per_m=0.5)

        assert pricing.cost_usd(input_tokens=0, output_tokens=0, cached_tokens=0) == 0.0


class TestBuildPricing:
    def test_missing_config_yields_no_pricing(self):
        assert build_pricing(None, "https://api.deepseek.com") is None
        assert build_pricing({}, "https://api.deepseek.com") is None

    def test_all_zero_prices_yield_no_pricing(self):
        config = {"input_per_m": 0, "output_per_m": 0, "cached_per_m": 0}

        assert build_pricing(config, "https://api.deepseek.com") is None

    def test_prices_apply_when_the_endpoint_matches(self):
        config = {
            "base_url": "https://api.deepseek.com",
            "input_per_m": 2.0,
            "output_per_m": 8.0,
        }

        pricing = build_pricing(config, "https://api.deepseek.com/")

        assert pricing is not None
        assert pricing.input_per_m == 2.0

    def test_prices_are_ignored_for_a_different_endpoint(self):
        """Switching providers must not silently reuse the old provider's rates."""
        config = {
            "base_url": "https://api.deepseek.com",
            "input_per_m": 2.0,
            "output_per_m": 8.0,
        }

        assert build_pricing(config, "https://api.openai.com/v1") is None

    def test_negative_price_is_rejected(self):
        config = {"input_per_m": -1.0, "output_per_m": 8.0}

        with pytest.raises(ValueError):
            build_pricing(config, "https://api.deepseek.com")

    def test_non_numeric_price_is_rejected(self):
        config = {"input_per_m": "免费", "output_per_m": 8.0}

        with pytest.raises(ValueError):
            build_pricing(config, "https://api.deepseek.com")


class TestNormalizeEndpoint:
    def test_trailing_slash_and_case_are_ignored(self):
        assert normalize_endpoint("https://API.DeepSeek.com/") == normalize_endpoint(
            "https://api.deepseek.com"
        )


class TestTokenStatsIntegration:
    def test_cost_is_none_without_pricing(self):
        stats = TokenStats()
        stats.add(1000, 500, 0)

        assert stats.cost_usd is None
        assert "未配置单价" in stats.summary()

    def test_cost_is_reported_with_pricing(self):
        stats = TokenStats(
            pricing=TokenPricing(input_per_m=2.0, output_per_m=8.0, cached_per_m=0.5)
        )
        stats.add(1_000_000, 0, 0)

        assert stats.cost_usd == pytest.approx(2.0)
        assert "未配置单价" not in stats.summary()


class TestFormatCostUsd:
    def test_none_shows_a_placeholder_not_zero(self):
        """"$0.000" would read as "this run was free", which is a lie."""
        assert format_cost_usd(None) == "未配置单价"

    def test_amount_is_formatted_in_usd(self):
        assert format_cost_usd(1.2345) == "$1.234"
