from core.model_catalog import (
    CUSTOM_PROVIDER,
    MODEL_PROVIDERS,
    pricing_for_model,
    provider_for_endpoint,
)


def test_deepseek_model_choices_include_pro_and_flash():
    assert [model for model, _ in MODEL_PROVIDERS["deepseek"].models] == [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
    ]


def test_gemini_model_choices_are_flash_models():
    models = [model for model, _ in MODEL_PROVIDERS["gemini"].models]
    assert models
    assert all("flash" in model for model in models)


def test_existing_builtin_configuration_is_migrated_to_its_provider():
    assert provider_for_endpoint("https://api.deepseek.com/", "deepseek-v4-flash") == "deepseek"


def test_non_builtin_configuration_stays_custom():
    assert provider_for_endpoint("https://example.com/v1", "my-model") == CUSTOM_PROVIDER


def test_each_builtin_model_has_a_usd_price():
    for provider in MODEL_PROVIDERS.values():
        for model, _ in provider.models:
            pricing = pricing_for_model(model)
            assert pricing is not None
            assert pricing.input_per_m > 0
            assert pricing.output_per_m > 0
