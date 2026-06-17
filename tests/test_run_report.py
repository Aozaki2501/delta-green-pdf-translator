from types import SimpleNamespace
import pytest

from core.run_report import (
    build_run_effect,
    build_run_manifest,
    render_run_effect_markdown,
)


def test_run_effect_computes_cache_and_cost_rates():
    stats = SimpleNamespace(
        input_tokens=1000,
        output_tokens=500,
        cached_tokens=250,
        api_calls=4,
        failed_calls=1,
        translation_cache_hits=2,
        cost_yuan=0.6,
    )

    effect = build_run_effect(
        stats,
        total_pages=5,
        translated_pages=3,
        failed_pages=[2],
        quality_issues=4,
        glossary_candidates=6,
        elapsed_seconds=12.5,
    )

    assert effect["cache_hit_rate"] == 0.25
    assert effect["cost_per_page"] == pytest.approx(0.2)
    assert effect["failed_pages"] == [2]


def test_run_effect_markdown_is_human_readable():
    markdown = render_run_effect_markdown({
        "total_pages": 2,
        "translated_pages": 2,
        "failed_pages": [],
        "quality_issues": 1,
        "glossary_candidates": 3,
        "api_calls": 2,
        "failed_calls": 0,
        "input_tokens": 100,
        "output_tokens": 50,
        "cached_tokens": 25,
        "cache_hit_rate": 0.25,
        "translation_cache_hits": 1,
        "cost_yuan": 0.12,
        "cost_per_page": 0.06,
    }, "测试")

    assert markdown.startswith("# 测试")
    assert "缓存命中率：25.0%" in markdown
    assert "平均每页：¥0.060" in markdown


def test_run_manifest_keeps_outputs_and_reports_separate():
    manifest = build_run_manifest(
        source_file="book.pdf",
        source_sha256="abc",
        provider="deepseek",
        model="model",
        page_range="1-2",
        formats=["html"],
        prompt_version="p1",
        extractor_version="e1",
        glossary_name="glossary.tsv",
        glossary_sha256="g1",
        status="completed",
        effect={"translated_pages": 2},
        output_files=["book.html"],
        internal_reports=["book_quality_report.md"],
        quality_report="book_quality_report.md",
        run_report="book_run_report.md",
    )

    assert manifest["outputs"] == ["book.html"]
    assert manifest["internal_reports"] == ["book_quality_report.md"]
    assert manifest["settings"]["prompt_version"] == "p1"
