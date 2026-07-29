import pytest

from core.typeset_profiles import get_typeset_profile, list_typeset_profiles


def test_profiles_keep_dg_and_kult_settings_isolated():
    dg = get_typeset_profile("delta_green")
    kult = get_typeset_profile("kult")

    dg_config = dg.build_config(document_title="DG", layout_hints_path=None)
    kult_config = kult.build_config(document_title="KULT", layout_hints_path=None)

    assert dg_config.profile_id == "delta_green"
    assert kult_config.profile_id == "kult"
    assert dg_config.source_language == "English"
    assert kult_config.source_language == "Swedish"
    assert dg_config.subtitle_color == "#dc2527"
    assert kult_config.subtitle_color == "#b8282f"
    assert "Delta Green" in dg.system_prompt
    assert "KULT" in kult.system_prompt
    assert "Delta Green" not in kult.system_prompt


def test_unknown_typeset_profile_fails_explicitly():
    with pytest.raises(ValueError, match="未知高保真排版配置"):
        get_typeset_profile("unknown")


def test_profile_registry_lists_both_supported_typesets():
    assert [profile.id for profile in list_typeset_profiles()] == ["delta_green", "kult"]
