from core.typeset_models import (
    PAGE_CONTENT_SCHEMA_VERSION,
    ContentBlock,
    PageContent,
    PageContentDocument,
    PageType,
    SemanticRole,
    StyledTextRun,
)
from core.typeset_quality import build_typeset_quality_report


def _document(translation: str) -> PageContentDocument:
    block = ContentBlock(
        id="b1",
        region_id="r1",
        role=SemanticRole.BODY_COLUMN,
        runs=[
            StyledTextRun("普通", 10.0, False, False, "#000000"),
            StyledTextRun("斜体", 10.0, False, True, "#000000"),
        ],
        source_text="普通斜体",
        translated_text=translation,
        translatable=True,
    )
    return PageContentDocument(
        PAGE_CONTENT_SCHEMA_VERSION,
        "book.pdf",
        1,
        [PageContent(0, PageType.SINGLE, [], [block])],
    )


def test_typeset_quality_flags_unmapped_mixed_emphasis():
    report = build_typeset_quality_report(_document("普通斜体"))

    assert any(issue.kind == "emphasis_unmapped" for issue in report.issues)


def test_typeset_quality_accepts_translated_emphasis_marker():
    report = build_typeset_quality_report(_document("普通<em>斜体</em>"))

    assert not any(issue.kind == "emphasis_unmapped" for issue in report.issues)
