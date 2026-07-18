import pytest

from core.output_validation import validate_translation_completeness


def test_validate_translation_completeness_allows_failed_text_page():
    result = validate_translation_completeness(
        pages_text={0: "Page one", 1: "Page two", 2: ""},
        translated_pages=[(0, "第一页")],
        failed_page_indexes={1},
        start_page=0,
        end_page=3,
    )

    assert result.expected_text_pages == 2
    assert result.translated_pages == 1
    assert result.failed_pages == [2]


def test_validate_translation_completeness_rejects_missing_text_page():
    with pytest.raises(ValueError, match="有正文但没有译文或失败记录"):
        validate_translation_completeness(
            pages_text={0: "Page one", 1: "Page two"},
            translated_pages=[(0, "第一页")],
            failed_page_indexes=set(),
            start_page=0,
            end_page=2,
        )


def test_validate_translation_completeness_rejects_duplicate_page():
    with pytest.raises(ValueError, match="重复页"):
        validate_translation_completeness(
            pages_text={0: "Page one"},
            translated_pages=[(0, "第一页"), (0, "第一页 again")],
            failed_page_indexes=set(),
            start_page=0,
            end_page=1,
        )
