"""Checks before merging translated pages into final outputs."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TranslationCompleteness:
    expected_text_pages: int
    translated_pages: int
    failed_pages: list[int]


def validate_translation_completeness(
    *,
    pages_text: dict[int, str],
    translated_pages: list[tuple[int, str]],
    failed_page_indexes: set[int],
    start_page: int,
    end_page: int,
) -> TranslationCompleteness:
    expected_range = set(range(start_page, end_page))
    seen_pages: set[int] = set()
    duplicates: list[int] = []
    out_of_range: list[int] = []
    translated_nonempty: set[int] = set()

    for page_num, translation in translated_pages:
        if page_num in seen_pages:
            duplicates.append(page_num)
        seen_pages.add(page_num)
        if page_num not in expected_range:
            out_of_range.append(page_num)
        if str(translation or "").strip():
            translated_nonempty.add(page_num)

    if duplicates:
        display = ", ".join(str(page + 1) for page in sorted(set(duplicates)))
        raise ValueError(f"导出前校验失败：重复页 {display}")
    if out_of_range:
        display = ", ".join(str(page + 1) for page in sorted(set(out_of_range)))
        raise ValueError(f"导出前校验失败：页码超出范围 {display}")

    source_text_pages = {
        page_num for page_num in expected_range
        if str(pages_text.get(page_num, "")).strip()
    }
    failed_in_range = {page for page in failed_page_indexes if page in expected_range}
    missing = sorted(source_text_pages - translated_nonempty - failed_in_range)
    if missing:
        display = ", ".join(str(page + 1) for page in missing[:30])
        raise ValueError(f"导出前校验失败：有正文但没有译文或失败记录的页 {display}")

    return TranslationCompleteness(
        expected_text_pages=len(source_text_pages),
        translated_pages=len(translated_nonempty),
        failed_pages=[page + 1 for page in sorted(failed_in_range)],
    )
