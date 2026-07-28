"""Built-in translation provider and model choices for the Web UI."""
from dataclasses import dataclass


CUSTOM_PROVIDER = "custom"


@dataclass(frozen=True)
class ModelProvider:
    label: str
    base_url: str
    models: tuple[tuple[str, str], ...]

    @property
    def default_model(self) -> str:
        return self.models[0][0]


@dataclass(frozen=True)
class ModelPricing:
    """Official standard-tier prices in USD per one million text tokens."""

    input_per_m: float
    output_per_m: float
    cached_per_m: float


MODEL_PROVIDERS = {
    "deepseek": ModelProvider(
        label="DeepSeek",
        base_url="https://api.deepseek.com",
        models=(
            ("deepseek-v4-pro", "DeepSeek V4 Pro"),
            ("deepseek-v4-flash", "DeepSeek V4 Flash"),
        ),
    ),
    "gemini": ModelProvider(
        label="Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        models=(
            ("gemini-2.5-flash", "Gemini 2.5 Flash"),
            ("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite"),
            ("gemini-3-flash-preview", "Gemini 3 Flash（预览）"),
        ),
    ),
}

MODEL_PRICING_USD = {
    "deepseek-v4-pro": ModelPricing(0.435, 0.87, 0.003625),
    "deepseek-v4-flash": ModelPricing(0.14, 0.28, 0.0028),
    "gemini-2.5-flash": ModelPricing(0.30, 2.50, 0.03),
    "gemini-2.5-flash-lite": ModelPricing(0.10, 0.40, 0.01),
    "gemini-3-flash-preview": ModelPricing(0.50, 3.00, 0.05),
}


def pricing_for_model(model: str) -> ModelPricing | None:
    """Return the known official USD price for a built-in model."""
    return MODEL_PRICING_USD.get(str(model or "").strip())


def provider_for_endpoint(base_url: str, model: str) -> str:
    """Return a built-in provider only for an exact saved configuration match."""
    normalized_url = str(base_url or "").strip().rstrip("/")
    normalized_model = str(model or "").strip()
    for provider_key, provider in MODEL_PROVIDERS.items():
        if normalized_url != provider.base_url.rstrip("/"):
            continue
        if any(model_id == normalized_model for model_id, _ in provider.models):
            return provider_key
    return CUSTOM_PROVIDER
