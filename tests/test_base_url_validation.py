"""The endpoint is validated before an API key or source text is sent to it.

A typo'd or plain-HTTP base_url used to be passed straight to the OpenAI client,
which put the API key and the full English source on the wire in clear text.
"""

import pytest

from core.utils import validate_base_url


class TestAcceptedEndpoints:
    def test_https_endpoint_is_accepted(self):
        assert validate_base_url("https://api.deepseek.com") == "https://api.deepseek.com"

    def test_surrounding_whitespace_is_stripped(self):
        assert validate_base_url("  https://api.deepseek.com  ") == "https://api.deepseek.com"

    def test_local_http_is_accepted(self):
        """A local model server has no network hop to eavesdrop on."""
        assert validate_base_url("http://localhost:11434/v1") == "http://localhost:11434/v1"
        assert validate_base_url("http://127.0.0.1:8000/v1") == "http://127.0.0.1:8000/v1"


class TestRejectedEndpoints:
    def test_empty_is_rejected(self):
        with pytest.raises(ValueError):
            validate_base_url("")

    def test_remote_plain_http_is_rejected(self):
        with pytest.raises(ValueError) as exc:
            validate_base_url("http://api.deepseek.com")

        assert "HTTPS" in str(exc.value)

    def test_missing_scheme_is_rejected(self):
        with pytest.raises(ValueError):
            validate_base_url("api.deepseek.com")

    def test_non_http_scheme_is_rejected(self):
        with pytest.raises(ValueError):
            validate_base_url("ftp://api.deepseek.com")

    def test_file_scheme_is_rejected(self):
        with pytest.raises(ValueError):
            validate_base_url("file:///etc/passwd")

    def test_scheme_without_host_is_rejected(self):
        with pytest.raises(ValueError):
            validate_base_url("https://")
