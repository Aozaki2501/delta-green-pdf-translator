from types import SimpleNamespace

import core.translator as translator_module
from core.translator import Translator, translate_batch_concurrent


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_cache_hit_tokens=0,
            ),
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="译文")
                )
            ],
        )


class _FakeClient:
    def __init__(self):
        self.completions = _FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


def test_pdf_glossary_goes_to_user_prompt_not_system_prompt():
    translator = Translator("test-key")
    fake_client = _FakeClient()
    translator.client = fake_client
    translator.set_glossary({"Delta Green": "绿色三角洲"})

    translator.translate_chunk("Delta Green agents arrive.", page_num=0)

    messages = fake_client.completions.calls[0]["messages"]
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]
    assert "Delta Green -> 绿色三角洲" not in system_prompt
    assert "Delta Green -> 绿色三角洲" in user_prompt


def test_markdown_glossary_goes_to_user_prompt_not_system_prompt():
    translator = Translator("test-key")
    fake_client = _FakeClient()
    translator.client = fake_client
    translator.set_glossary({"Handler": "管理者"})

    translator.translate_block("The Handler speaks.", block_index=0)

    messages = fake_client.completions.calls[0]["messages"]
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]
    assert "Handler -> 管理者" not in system_prompt
    assert "Handler -> 管理者" in user_prompt


def test_core_glossary_is_stable_user_prompt_prefix():
    translator = Translator("test-key")
    fake_client = _FakeClient()
    translator.client = fake_client
    translator.set_glossary({
        "Delta Green": "绿色三角洲",
        "Handler": "管理者",
    })
    translator.set_core_glossary({"Delta Green": "绿色三角洲"})

    translator.translate_chunk("Delta Green agents meet a Handler.", page_num=0)

    messages = fake_client.completions.calls[0]["messages"]
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]
    assert "Delta Green -> 绿色三角洲" not in system_prompt
    assert user_prompt.startswith(
        "Use these core glossary entries throughout this translation job:"
    )
    assert user_prompt.index("Delta Green -> 绿色三角洲") < user_prompt.index(
        "Translate the following"
    )
    assert user_prompt.count("Delta Green -> 绿色三角洲") == 1
    assert "Handler -> 管理者" in user_prompt


class _BatchTranslator:
    def __init__(self):
        self.call_order = []

    def translate_chunk(self, text, page_num=None, prev_context="", cache=None):
        self.call_order.append(page_num)
        return f"译文 {page_num + 1}"


class _BatchTracker:
    def __init__(self):
        self.completed = {}
        self.failed = {}

    def is_completed(self, page_num):
        return page_num in self.completed

    def get_translation(self, page_num):
        return self.completed.get(page_num, "")

    def mark_completed(self, page_num, translation):
        self.completed[page_num] = translation

    def mark_failed(self, page_num, translation):
        self.failed[page_num] = translation


def test_batch_translation_warms_first_page_before_parallel_work():
    translator = _BatchTranslator()
    tracker = _BatchTracker()
    pages_data = [
        (0, "First page", ""),
        (1, "Second page", ""),
        (2, "Third page", ""),
    ]

    results = translate_batch_concurrent(
        pages_data,
        translator,
        tracker,
        max_workers=3,
    )

    assert translator.call_order[0] == 0
    assert set(translator.call_order) == {0, 1, 2}
    assert results == {
        0: "译文 1",
        1: "译文 2",
        2: "译文 3",
    }


def test_batch_translation_uses_rate_limit_and_cooldown(monkeypatch):
    rate_calls = []
    sleeps = []

    class FakeRateLimiter:
        def __init__(self, calls_per_minute):
            rate_calls.append(("init", calls_per_minute))

        def wait_if_needed(self):
            rate_calls.append(("wait", None))

    monkeypatch.setattr(translator_module, "RateLimiter", FakeRateLimiter)
    monkeypatch.setattr(translator_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    translator = _BatchTranslator()
    tracker = _BatchTracker()
    pages_data = [
        (0, "First page", ""),
        (1, "Second page", ""),
        (2, "Third page", ""),
    ]

    translate_batch_concurrent(
        pages_data,
        translator,
        tracker,
        max_workers=2,
        rate_limit=7,
        cooldown=0.25,
    )

    assert ("init", 7) in rate_calls
    assert len([call for call in rate_calls if call[0] == "wait"]) == 3
    assert sleeps == [0.25]
