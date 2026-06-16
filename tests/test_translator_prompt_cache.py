from types import SimpleNamespace

from core.translator import Translator


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
