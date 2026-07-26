"""Truncated model output must fail loudly instead of being cached as a translation.

Before this check, finish_reason="length" was indistinguishable from a normal
completion: the half-finished text was returned, written to the progress file,
and exported. The page looked translated and the run reported success.
"""

from types import SimpleNamespace

from core.constants import TRANSLATION_FAILURE_PREFIX
from core.translator import Translator, TruncatedResponseError


def _response(content: str, finish_reason: str = "stop"):
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            prompt_cache_hit_tokens=0,
        ),
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
    )


class _TruncatingCompletions:
    def __init__(self, finish_reason="length", content="这是被截断的半"):
        self.calls = []
        self.finish_reason = finish_reason
        self.content = content

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _response(self.content, self.finish_reason)


class _FakeClient:
    def __init__(self, completions):
        self.completions = completions
        self.chat = SimpleNamespace(completions=completions)


class _RecordingCache:
    def __init__(self):
        self.written = {}

    def get_cached_prompt_translation(self, key):
        return ""

    def mark_cached_prompt_translation(self, key, translation):
        self.written[key] = translation


class TestTruncationIsDetected:
    def test_translate_chunk_returns_failure_marker(self):
        translator = Translator("test-key")
        translator.client = _FakeClient(_TruncatingCompletions())

        result = translator.translate_chunk("A long English page.", page_num=3)

        assert result.startswith(TRANSLATION_FAILURE_PREFIX)
        assert "截断" in result
        assert "这是被截断的半" not in result

    def test_translate_block_returns_failure_marker(self):
        translator = Translator("test-key")
        translator.client = _FakeClient(_TruncatingCompletions())

        result = translator.translate_block("A long English block.", block_index=1)

        assert result.startswith(TRANSLATION_FAILURE_PREFIX)
        assert "这是被截断的半" not in result

    def test_truncated_output_is_never_cached(self):
        translator = Translator("test-key")
        translator.client = _FakeClient(_TruncatingCompletions())
        cache = _RecordingCache()

        translator.translate_block("A long English block.", block_index=1, cache=cache)

        assert cache.written == {}

    def test_truncation_is_not_retried(self):
        """Retrying the same over-long prompt just burns tokens for the same cut."""
        completions = _TruncatingCompletions()
        translator = Translator("test-key")
        translator.client = _FakeClient(completions)

        translator.translate_chunk("A long English page.", page_num=0)

        assert len(completions.calls) == 1

    def test_truncation_counts_as_a_failure(self):
        translator = Translator("test-key")
        translator.client = _FakeClient(_TruncatingCompletions())

        translator.translate_chunk("A long English page.", page_num=0)

        assert translator.stats.failed_calls == 1

    def test_normal_completion_still_succeeds(self):
        translator = Translator("test-key")
        translator.client = _FakeClient(
            _TruncatingCompletions(finish_reason="stop", content="完整译文")
        )
        cache = _RecordingCache()

        result = translator.translate_block("Short block.", block_index=0, cache=cache)

        assert result == "完整译文"
        assert list(cache.written.values()) == ["完整译文"]


class TestTruncatedResponseError:
    def test_error_names_the_token_limit(self):
        translator = Translator("test-key")
        translator.client = _FakeClient(_TruncatingCompletions())

        try:
            translator._read_completion(
                _response("half", "length"), max_tokens=4096
            )
        except TruncatedResponseError as exc:
            assert "4096" in str(exc)
        else:
            raise AssertionError("expected TruncatedResponseError")

    def test_empty_choices_raise(self):
        translator = Translator("test-key")
        response = SimpleNamespace(usage=None, choices=[])

        try:
            translator._read_completion(response, max_tokens=4096)
        except RuntimeError as exc:
            assert "choices" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")
