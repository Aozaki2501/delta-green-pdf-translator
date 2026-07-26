"""Configurable token unit prices.

Unit prices belong to a specific provider endpoint, not to this project. The
old hard-coded DeepSeek prices produced confident but wrong CNY amounts as soon
as the user pointed ``base_url`` at another OpenAI-compatible service, so a
price is only ever applied when it was configured for the endpoint in use.

Dependencies: standard library only.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenPricing:
    """CNY per one million tokens for one API endpoint."""

    input_per_m: float
    output_per_m: float
    cached_per_m: float = 0.0
    base_url: str = ""

    def cost_yuan(self, *, input_tokens: int, output_tokens: int,
                  cached_tokens: int = 0) -> float:
        billed_input = max(0, int(input_tokens) - int(cached_tokens))
        return (
            billed_input * self.input_per_m / 1_000_000
            + int(output_tokens) * self.output_per_m / 1_000_000
            + int(cached_tokens) * self.cached_per_m / 1_000_000
        )


def normalize_endpoint(base_url: str) -> str:
    """Normalize a base URL so trivial spelling differences still match."""
    return str(base_url or "").strip().rstrip("/").lower()


def build_pricing(config, base_url: str) -> TokenPricing | None:
    """Build pricing for ``base_url`` from a config mapping.

    Returns None when no prices are configured, when they are incomplete, or
    when they were recorded for a different endpoint — displaying an amount
    computed from another provider's price list would be misleading.

    Expected mapping shape::

        {"base_url": "https://api.deepseek.com",
         "input_per_m": 1.0, "output_per_m": 4.0, "cached_per_m": 0.1}
    """
    if not isinstance(config, dict) or not config:
        return None

    try:
        input_per_m = float(config.get("input_per_m", 0) or 0)
        output_per_m = float(config.get("output_per_m", 0) or 0)
        cached_per_m = float(config.get("cached_per_m", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("单价必须是数字：input_per_m / output_per_m / cached_per_m") from exc

    if min(input_per_m, output_per_m, cached_per_m) < 0:
        raise ValueError("单价不能为负数")
    if input_per_m <= 0 and output_per_m <= 0:
        return None

    configured_endpoint = config.get("base_url", "")
    if configured_endpoint and normalize_endpoint(configured_endpoint) != normalize_endpoint(base_url):
        return None

    return TokenPricing(
        input_per_m=input_per_m,
        output_per_m=output_per_m,
        cached_per_m=cached_per_m,
        base_url=normalize_endpoint(base_url),
    )


def format_cost_yuan(cost: float | None, placeholder: str = "未配置单价") -> str:
    """Render a cost for display, or a placeholder when prices are unknown."""
    if cost is None:
        return placeholder
    return f"¥{cost:.3f}"
