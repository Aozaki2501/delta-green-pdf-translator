import json

import pytest

from translate_pdf import load_config


def test_load_config_accepts_supported_pdf_keys(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "pdf": "book.pdf",
            "api_key": "sk-test",
            "workers": 8,
            "rate_limit": 60,
            "cooldown": 1.0,
            "retranslate_pages": "2,4-5",
        }),
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config["workers"] == 8
    assert config["rate_limit"] == 60
    assert config["cooldown"] == 1.0
    assert config["retranslate_pages"] == "2,4-5"


def test_load_config_rejects_unsupported_pdf_keys(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "pdf": "book.pdf",
            "api_key": "sk-test",
            "max_split_depth": 10,
        }),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        load_config(str(config_path))
