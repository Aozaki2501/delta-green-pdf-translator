"""Run manifest and human-readable effect report helpers."""

import json
from pathlib import Path


def build_run_effect(
    stats,
    *,
    total_pages: int,
    translated_pages: int,
    failed_pages: list[int],
    quality_issues: int,
    glossary_candidates: int,
    elapsed_seconds: float,
) -> dict:
    input_tokens = int(getattr(stats, "input_tokens", 0) or 0)
    cached_tokens = int(getattr(stats, "cached_tokens", 0) or 0)
    cost_yuan = float(getattr(stats, "cost_yuan", 0.0) or 0.0)
    translated_count = max(0, int(translated_pages or 0))
    return {
        "total_pages": int(total_pages or 0),
        "translated_pages": translated_count,
        "failed_pages": list(failed_pages or []),
        "quality_issues": int(quality_issues or 0),
        "glossary_candidates": int(glossary_candidates or 0),
        "elapsed_seconds": float(elapsed_seconds or 0.0),
        "api_calls": int(getattr(stats, "api_calls", 0) or 0),
        "failed_calls": int(getattr(stats, "failed_calls", 0) or 0),
        "input_tokens": input_tokens,
        "output_tokens": int(getattr(stats, "output_tokens", 0) or 0),
        "cached_tokens": cached_tokens,
        "cache_hit_rate": cached_tokens / input_tokens if input_tokens else 0.0,
        "translation_cache_hits": int(getattr(stats, "translation_cache_hits", 0) or 0),
        "cost_yuan": cost_yuan,
        "cost_per_page": cost_yuan / translated_count if translated_count else 0.0,
    }


def render_run_effect_markdown(effect: dict, title: str = "") -> str:
    heading = f"# {title} — 效果报告" if title else "# 效果报告"
    failed_pages = effect.get("failed_pages") or []
    failed_text = ", ".join(str(page) for page in failed_pages[:30]) if failed_pages else "无"
    return "\n".join([
        heading,
        "",
        "## 翻译结果",
        "",
        f"- 检查页数：{effect.get('total_pages', 0)}",
        f"- 有译文页数：{effect.get('translated_pages', 0)}",
        f"- 失败页：{failed_text}",
        f"- 质量提示：{effect.get('quality_issues', 0)}",
        f"- 术语候选：{effect.get('glossary_candidates', 0)}",
        "",
        "## 成本与缓存",
        "",
        f"- API 调用：{effect.get('api_calls', 0)}",
        f"- API 失败：{effect.get('failed_calls', 0)}",
        f"- 输入 Token：{effect.get('input_tokens', 0):,}",
        f"- 输出 Token：{effect.get('output_tokens', 0):,}",
        f"- 缓存命中 Token：{effect.get('cached_tokens', 0):,}",
        f"- 缓存命中率：{effect.get('cache_hit_rate', 0.0):.1%}",
        f"- 本地提示缓存命中：{effect.get('translation_cache_hits', 0)}",
        f"- 估算费用：¥{effect.get('cost_yuan', 0.0):.3f}",
        f"- 平均每页：¥{effect.get('cost_per_page', 0.0):.3f}",
        "",
    ])


def write_run_effect_report(effect: dict, output_path: str, title: str = "") -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(render_run_effect_markdown(effect, title))


def build_run_manifest(
    *,
    source_file: str,
    source_sha256: str,
    provider: str,
    model: str,
    page_range: str,
    formats: list[str],
    prompt_version: str,
    extractor_version: str,
    glossary_name: str,
    glossary_sha256: str,
    status: str,
    effect: dict,
    output_files: list[str],
    internal_reports: list[str],
    quality_report: str,
    run_report: str,
) -> dict:
    return {
        "source": {
            "file": source_file,
            "sha256": source_sha256,
        },
        "settings": {
            "provider": provider,
            "model": model,
            "page_range": page_range,
            "formats": list(formats or []),
            "prompt_version": prompt_version,
            "extractor_version": extractor_version,
            "glossary": glossary_name or "",
            "glossary_sha256": glossary_sha256 or "",
        },
        "status": status,
        "effect": effect,
        "quality_report": quality_report,
        "run_report": run_report,
        "outputs": list(output_files or []),
        "internal_reports": list(internal_reports or []),
    }


def write_run_manifest(manifest: dict, output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
