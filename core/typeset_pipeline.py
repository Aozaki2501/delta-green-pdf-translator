"""
Typeset pipeline orchestrator (Phase A → B → C → D → E).

Coordinates the full typeset reflow pipeline: page structure extraction,
semantic analysis, translation, HTML rebuild, and PDF export. Supports
checkpoint/resume via intermediate JSON files and progress tracking.

Dependencies:
    core.page_structure (Phase A)
    core.semantic_analyzer (Phase B)
    core.typeset_translation (Phase C)
    exporters.typeset_html (Phase D)
    exporters.typeset_pdf (Phase E)
    core.typeset_models (data models)
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Callable

from core.constants import PROMPT_VERSION, TRANSLATION_TEMPERATURE
from core.typeset_models import (
    PAGE_CONTENT_SCHEMA_VERSION,
    PAGE_STRUCTURE_SCHEMA_VERSION,
    PageContentDocument,
    PageStructureDocument,
    TypesetConfig,
    TypesetResult,
)
from core.utils import atomic_output_path

logger = logging.getLogger(__name__)

# Project root, used to bound where layout hints may be read from.
APP_DIR = Path(__file__).resolve().parent.parent
TRANSLATION_CONTEXT_VERSION = "typeset-translation-v5"
SEMANTIC_CONTEXT_VERSION = "typeset-semantic-v3"


def _report_file_name(path: str | None) -> str:
    """Reduce a path to its file name for reports.

    _typeset_report.json is shipped alongside the outputs, so it must not carry
    the local absolute path of the machine that produced it.
    """
    if not path:
        return ""
    return Path(str(path)).name


def _is_image_overlay_text_block(block, page_structure) -> bool:
    """Identify tiny PDF text spans that are part of a foreground image.

    This is intentionally narrow: only one- or two-character body spans that
    materially overlap a non-background image are ignored. Normal prose and
    decorative drop caps remain translatable.
    """
    if getattr(block, "layout_mode", "") == "image_overlay_text":
        return True
    if getattr(getattr(block, "role", None), "value", "") != "body_column":
        return False
    text = (getattr(block, "source_text", "") or "").strip()
    bbox = getattr(block, "bbox", None)
    if not text or len(text) > 2 or not bbox or len(bbox) != 4:
        return False
    block_area = _bbox_area(bbox)
    page_area = max(1.0, float(page_structure.width) * float(page_structure.height))
    if block_area <= 0:
        return False
    for image in getattr(page_structure, "images", []):
        image_bbox = getattr(image, "bbox", None)
        if not image_bbox or len(image_bbox) != 4:
            continue
        image_area = _bbox_area(image_bbox)
        if image_area <= page_area * 0.02 or image_area >= page_area * 0.9:
            continue
        overlap = _bbox_intersection_area(bbox, image_bbox)
        if overlap / block_area >= 0.35:
            return True
    return False


def _bbox_area(bbox: list[float]) -> float:
    if len(bbox) != 4:
        return 0.0
    return max(0.0, float(bbox[2]) - float(bbox[0])) * max(
        0.0, float(bbox[3]) - float(bbox[1])
    )


def _bbox_intersection_area(first: list[float], second: list[float]) -> float:
    if len(first) != 4 or len(second) != 4:
        return 0.0
    width = max(
        0.0,
        min(float(first[2]), float(second[2]))
        - max(float(first[0]), float(second[0])),
    )
    height = max(
        0.0,
        min(float(first[3]), float(second[3]))
        - max(float(first[1]), float(second[1])),
    )
    return width * height


# ---------------------------------------------------------------------------
# TypesetPipeline
# ---------------------------------------------------------------------------


class TypesetPipeline:
    """Typeset reflow pipeline orchestrator.

    Executes the full pipeline: Phase A (structure extraction) → Phase B
    (semantic analysis) → Phase C (translation) → Phase D (HTML rebuild)
    → Phase E (PDF export). Supports checkpoint/resume by checking
    intermediate files and their schema versions.

    All typeset outputs use _typeset suffix.
    """

    def __init__(
        self,
        pdf_path: str,
        output_dir: str,
        translator,
        glossary: dict,
        config: TypesetConfig | None = None,
        layout_hints_generator: Callable | None = None,
    ):
        """Initialize the typeset pipeline.

        Args:
            pdf_path: Path to the source PDF file.
            output_dir: Output directory for all generated files.
            translator: Translator instance with translate_chunk() method.
            glossary: {english_term: chinese_translation} dictionary.
            config: Typeset configuration (fonts, line height, etc.).
                    Uses defaults if None.
        """
        self.pdf_path = str(pdf_path)
        self.output_dir = Path(output_dir)
        self.translator = translator
        self.config = config or TypesetConfig()
        self.glossary = self._effective_glossary(glossary)
        self.layout_hints_generator = layout_hints_generator

        # Derive file stem from PDF name
        self._pdf_stem = Path(self.pdf_path).stem

        # Output file paths (all use _typeset suffix)
        self._page_structure_path = self.output_dir / "page_structure.json"
        self._page_content_path = self.output_dir / "page_content.json"
        self._page_content_hinted_path = self.output_dir / "page_content_hinted.json"
        self._page_content_translated_path = (
            self.output_dir / "page_content_translated.json"
        )
        self._page_visuals_manifest_path = self.output_dir / "page_visuals.json"
        self._html_path = (
            self.output_dir / f"{self._pdf_stem}_typeset.html"
        )
        self._reading_html_path = (
            self.output_dir / f"{self._pdf_stem}_reading.html"
        )
        self._pdf_output_path = (
            self.output_dir / f"{self._pdf_stem}_typeset.pdf"
        )
        self._progress_path = (
            self.output_dir / f"{self._pdf_stem}_typeset.progress.json"
        )
        self._translation_context_path = (
            self.output_dir / f"{self._pdf_stem}_typeset.translation-context.json"
        )
        self._semantic_context_path = self.output_dir / "page_content.context.json"
        self._report_path = (
            self.output_dir / f"{self._pdf_stem}_typeset_report.json"
        )
        self._layout_report_path = (
            self.output_dir / f"{self._pdf_stem}_typeset_layout_issues.json"
        )
        self._layout_repair_path = (
            self.output_dir / f"{self._pdf_stem}_typeset_layout_repair_targets.json"
        )
        self._quality_report_path = (
            self.output_dir / f"{self._pdf_stem}_typeset_quality.md"
        )
        self._quality_report_json_path = (
            self.output_dir / f"{self._pdf_stem}_typeset_quality.json"
        )

        # Pipeline state
        self._start_page: int = 0
        self._end_page: int | None = None
        self._progress_callback: Callable | None = None
        self._errors: list[str] = []
        self._source_sha256_cache: str | None = None
        self._source_page_count_cache: int | None = None
        self._layout_repair_attempt: int = 0

    def _effective_glossary(self, supplied_glossary: dict | None) -> dict:
        """Add profile-owned terminology without changing the caller's glossary."""
        supplied = dict(supplied_glossary or {})
        if self.config.profile_id != "kult":
            return supplied
        from core.glossary import load_glossary

        built_in_path = APP_DIR / "assets" / "glossaries" / "kult_swedish.tsv"
        built_in = load_glossary(str(built_in_path))
        return {**built_in, **supplied}

    def _translation_context_signature(self) -> str:
        translator_class = type(self.translator)
        payload = {
            "version": TRANSLATION_CONTEXT_VERSION,
            "source": self._source_context_identity(),
            "prompt_version": PROMPT_VERSION,
            "temperature": TRANSLATION_TEMPERATURE,
            "profile_id": self.config.profile_id,
            "source_language": self.config.source_language,
            "preserve_emphasis": True,
            "glossary": sorted(self.glossary.items()),
            "semantic_context": self._semantic_context_signature(),
            "translator": {
                "class": f"{translator_class.__module__}.{translator_class.__qualname__}",
                "model": str(getattr(self.translator, "model", "") or ""),
                "base_url": str(getattr(self.translator, "base_url", "") or ""),
                "system_prompt": str(
                    getattr(self.translator, "system_prompt", "") or ""
                ),
            },
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _semantic_context_signature(self) -> str:
        payload = {
            "version": SEMANTIC_CONTEXT_VERSION,
            "source": self._source_context_identity(),
            "profile_id": self.config.profile_id,
            "source_language": self.config.source_language,
            "accent_heading_colors": list(self.config.accent_heading_colors),
            "body_font_size_pt": self.config.body_font_size_pt,
            "display_font_size_pt": self.config.display_font_size_pt,
            "section_font_size_pt": self.config.section_font_size_pt,
            "subsection_font_size_pt": self.config.subsection_font_size_pt,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _source_context_identity(self) -> dict:
        source = Path(self.pdf_path)
        return {
            "file_name": source.name,
            "sha256": self._current_source_sha256() if source.is_file() else "",
            "start_page": int(self._start_page),
            "end_page": None if self._end_page is None else int(self._end_page),
        }

    def _has_current_translation_context(self) -> bool:
        if not self._translation_context_path.exists():
            return False
        try:
            data = json.loads(self._translation_context_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return data.get("signature") == self._translation_context_signature()

    def _write_translation_context(self) -> None:
        self._write_context_file(
            self._translation_context_path,
            {"signature": self._translation_context_signature()},
        )

    def _has_current_semantic_context(self) -> bool:
        if not self._semantic_context_path.exists():
            return False
        try:
            data = json.loads(self._semantic_context_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return data.get("signature") == self._semantic_context_signature()

    def _write_semantic_context(self) -> None:
        self._write_context_file(
            self._semantic_context_path,
            {"signature": self._semantic_context_signature()},
        )

    @staticmethod
    def _write_context_file(path: Path, payload: dict) -> None:
        TypesetPipeline._write_text_file(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
        )

    @staticmethod
    def _write_text_file(path: Path, text: str) -> None:
        with atomic_output_path(path) as candidate:
            candidate.write_text(text, encoding="utf-8")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        start_page: int = 0,
        end_page: int | None = None,
        progress_callback: Callable[[str, int, int], None] | None = None,
        export_pdf: bool = True,
        export_typeset_html: bool = True,
        export_reading_html: bool = False,
    ) -> TypesetResult:
        """Execute the full typeset pipeline.

        Runs Phase A → B → C → D, and optionally Phase E (PDF export),
        sequentially. Supports checkpoint/resume: if intermediate files
        exist and have matching schema versions, the corresponding phase is
        skipped.

        Args:
            start_page: First page index (0-based, inclusive).
            end_page: Last page index (exclusive). None = all pages.
            progress_callback: Optional callback(phase_name, done, total).
            export_pdf: Whether to run Phase E and produce a PDF. PDF export
                        also creates the fixed-page HTML it renders from.
            export_typeset_html: Whether to emit the fixed-page HTML. PDF
                                 export always requires and creates it.
            export_reading_html: Whether to emit the responsive illustrated
                                 reading HTML from the same translated blocks.

        Returns:
            TypesetResult with paths and statistics.
        """
        self._start_page = start_page
        self._end_page = end_page
        self._progress_callback = progress_callback
        self._errors = []
        self._layout_repair_attempt = 0

        if not (export_pdf or export_typeset_html or export_reading_html):
            raise ValueError("至少选择一种图文重绘输出格式")

        self.output_dir.mkdir(parents=True, exist_ok=True)

        total_phases = 5 if export_pdf else 4
        self._report_progress("pipeline", 0, total_phases)

        # Phase A: Page structure extraction
        structure = self.run_phase_a()
        self._report_progress("pipeline", 1, total_phases)

        # Phase B: Semantic analysis
        content = self.run_phase_b(structure)
        self.generate_layout_hints(structure, content)
        content = self.apply_layout_hints(structure, content)
        self._report_progress("pipeline", 2, total_phases)

        # Phase C: Translation
        translated_content = self.run_phase_c(content)
        self._report_progress("pipeline", 3, total_phases)

        # Phase D: selected HTML rebuilds share the same source translation.
        html_path = None
        if export_typeset_html or export_pdf:
            self.config.reading_html_href = (
                self._reading_html_path.name if export_reading_html else None
            )
            html_path = self.run_phase_d(structure, translated_content)
        reading_html_path = None
        if export_reading_html:
            reading_html_path = self.run_phase_reading_d(structure, translated_content)
        self._report_progress("pipeline", 4, total_phases)

        # Phase E: PDF export (optional; HTML is always emitted)
        pdf_path = self.run_phase_e(html_path) if export_pdf and html_path else None
        if export_pdf:
            self._report_progress("pipeline", 5, total_phases)

        # Build result
        result = self._build_result(
            structure,
            translated_content,
            html_path,
            pdf_path,
            reading_html_path=reading_html_path,
        )

        # Generate error report
        self._write_report(result)

        return result

    def run_phase_a(self) -> PageStructureDocument:
        """Phase A: Page structure extraction.

        Extracts background, images, decorations, and text regions from
        the PDF. Reuses existing page_structure.json if schema version
        matches.

        Returns:
            PageStructureDocument with all page structures.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Check for existing page_structure.json with valid schema
        existing = self._load_existing_structure()
        if existing is not None:
            logger.info("Phase A: 复用已有 page_structure.json")
            self._ensure_page_visuals(existing)
            return existing

        from core.page_structure import PageStructureExtractor

        logger.info("Phase A: 提取页面结构...")
        with PageStructureExtractor(self.pdf_path, str(self.output_dir)) as extractor:
            structure = extractor.extract(
                start_page=self._start_page,
                end_page=self._end_page,
            )

        # Save to file
        self._write_text_file(self._page_structure_path, structure.to_json())
        self._ensure_page_visuals(structure, force_rebuild=True)
        self._mark_phase_completed("A")
        return structure

    def run_phase_b(self, structure: PageStructureDocument) -> PageContentDocument:
        """Phase B: Semantic analysis.

        Analyzes text regions for semantic roles, classifies page types,
        and extracts styled text. Reuses existing page_content.json if
        schema version matches.

        Args:
            structure: PageStructureDocument from Phase A.

        Returns:
            PageContentDocument with semantic content.
        """
        # Check for existing page_content.json with valid schema
        existing = self._load_existing_content()
        if existing is not None:
            normalized = self._normalize_image_overlay_blocks(existing, structure)
            if normalized is not existing:
                self._write_text_file(
                    self._page_content_path, normalized.to_json()
                )
            existing = normalized
            logger.info("Phase B: 复用已有 page_content.json")
            return existing

        from core.semantic_analyzer import SemanticAnalyzer

        logger.info("Phase B: 语义化分析...")
        with SemanticAnalyzer(
            self.pdf_path,
            str(self.output_dir),
            accent_heading_colors=self.config.accent_heading_colors,
        ) as analyzer:
            content = analyzer.analyze_document(structure)

        content = self._normalize_image_overlay_blocks(content, structure)

        # Save to file
        self._write_text_file(self._page_content_path, content.to_json())
        self._write_semantic_context()
        self._mark_phase_completed("B")
        return content

    def generate_layout_hints(
        self,
        structure: PageStructureDocument,
        content: PageContentDocument,
    ) -> Path | None:
        """Run an optional generator that writes layout_hints.json."""
        if self.layout_hints_generator is None:
            return None
        if self.config.layout_hints_path:
            return None

        output_path = self.output_dir / "layout_hints.json"
        generated = self.layout_hints_generator(
            structure,
            content,
            output_path,
        )
        return Path(generated) if generated else output_path

    def apply_layout_hints(
        self,
        structure: PageStructureDocument,
        content: PageContentDocument,
    ) -> PageContentDocument:
        """Apply optional layout_hints.json before translation and rendering."""
        hints_path = self._resolve_layout_hints_path()
        if hints_path is None:
            return content

        from core.layout_hints import LayoutHints, apply_hints_to_content

        logger.info(f"应用 layout hints：{hints_path}")
        hints = LayoutHints.from_file(hints_path)
        hinted = apply_hints_to_content(content, hints, structure)
        self._write_text_file(self._page_content_hinted_path, hinted.to_json())
        return hinted

    def run_phase_c(self, content: PageContentDocument) -> PageContentDocument:
        """Phase C: Translation.

        Translates semantic content blocks using the existing Translator
        module. Supports checkpoint/resume via progress file. Reuses
        existing translation progress when source text matches.

        Args:
            content: PageContentDocument from Phase B.

        Returns:
            PageContentDocument with translated_text populated.
        """
        from core.typeset_translation import (
            TypesetTranslationProgress,
            translate_typeset_content,
            save_translated_content,
        )

        # Check for existing translated content with valid schema
        existing = self._load_existing_translated_content()
        if existing is not None:
            logger.info("Phase C: 复用已有 page_content_translated.json")
            self._write_typeset_quality_report(existing)
            return existing

        logger.info("Phase C: 翻译...")

        # Load or create progress file
        progress = TypesetTranslationProgress(
            str(self._progress_path),
            context_signature=self._translation_context_signature(),
        )

        # Translation callback wrapper
        def translation_callback(done: int, total: int, unit_id: str, success: bool):
            if self._progress_callback:
                self._progress_callback("translation", done, total)
            if not success:
                self._errors.append(f"翻译失败：{unit_id}")

        translated = translate_typeset_content(
            content=content,
            translator=self.translator,
            progress=progress,
            glossary=self.glossary,
            progress_callback=translation_callback,
            max_workers=self.config.translation_concurrency,
            preserve_emphasis=True,
        )
        self._ensure_no_translation_failed(translated, progress)

        # Save translated content
        save_translated_content(
            translated, str(self._page_content_translated_path)
        )
        self._write_translation_context()
        self._write_typeset_quality_report(translated)
        self._mark_phase_completed("C")
        return translated

    def repair_overflow_translations(
        self,
        target_groups: dict[str, dict],
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> PageContentDocument:
        """Retranslate selected shared targets without rerunning phases A–C.

        Each group maps all blocks that share one measured container to explicit
        capacity, template signature, and constraint values.  The existing
        translated document is the source of all unselected text.
        """
        from core.typeset_translation import (
            TypesetTranslationProgress,
            save_translated_content,
            translate_overflow_groups,
        )

        existing = self._load_existing_translated_content(allow_layout_hints=True)
        if existing is None:
            raise RuntimeError("没有可复用的完整图文重绘译文，不能只修复溢出区域")

        progress = TypesetTranslationProgress(
            str(self._progress_path),
            context_signature=self._translation_context_signature(),
        )

        def repair_callback(done: int, total: int, _unit_id: str, success: bool):
            if progress_callback:
                progress_callback("translation", done, total)
            if not success:
                self._errors.append(f"溢出区域翻译失败：{_unit_id}")

        repaired = translate_overflow_groups(
            content=existing,
            translator=self.translator,
            progress=progress,
            glossary=self.glossary,
            target_groups=target_groups,
            progress_callback=repair_callback,
            preserve_emphasis=True,
        )
        save_translated_content(repaired, str(self._page_content_translated_path))
        self._write_translation_context()
        self._write_typeset_quality_report(repaired)
        self._mark_phase_completed("C")
        return repaired

    def _write_typeset_quality_report(
        self,
        content: PageContentDocument,
    ) -> None:
        from core.typeset_quality import (
            build_typeset_quality_report,
            write_typeset_quality_report,
        )

        report = build_typeset_quality_report(content, self.glossary)
        write_typeset_quality_report(
            report,
            self._quality_report_path,
            self._quality_report_json_path,
        )

    def repair_layout_overflows(
        self,
        *,
        start_page: int = 0,
        end_page: int | None = None,
        progress_callback: Callable[[str, int, int], None] | None = None,
        export_pdf: bool = False,
        export_typeset_html: bool = True,
        export_reading_html: bool = False,
        max_rounds: int = 2,
    ) -> TypesetResult:
        """Repair the current layout manifest without retranslating the book.

        The browser-generated manifest is the only authority for the selected
        blocks and their measured capacity.  A new browser check always runs
        after the selected translations are replaced.
        """
        if not (export_pdf or export_typeset_html or export_reading_html):
            raise ValueError("至少选择一种图文重绘输出格式")
        if not isinstance(max_rounds, int) or max_rounds < 1:
            raise ValueError("max_rounds 必须是正整数")

        self._start_page = start_page
        self._end_page = end_page
        self._progress_callback = progress_callback
        self._errors = []
        self.output_dir.mkdir(parents=True, exist_ok=True)

        groups, prior_attempt = self._load_layout_repair_groups()
        total_phases = 4 if export_pdf else 3
        self._report_progress("pipeline", 0, total_phases)

        structure = self.run_phase_a()
        self._report_progress("pipeline", 1, total_phases)

        repaired_content: PageContentDocument | None = None
        html_path = None
        for round_index in range(max_rounds):
            if round_index:
                groups, prior_attempt = self._load_layout_repair_groups()
            self._layout_repair_attempt = prior_attempt + 1
            repaired_content = self.repair_overflow_translations(
                groups,
                progress_callback=progress_callback,
            )
            self._report_progress("pipeline", 2, total_phases)
            if not (export_typeset_html or export_pdf):
                break
            self.config.reading_html_href = (
                self._reading_html_path.name if export_reading_html else None
            )
            try:
                html_path = self.run_phase_d(structure, repaired_content)
                break
            except RuntimeError as exc:
                if not str(exc).startswith("typeset layout overflow:"):
                    raise
                if round_index + 1 >= max_rounds:
                    raise RuntimeError(
                        f"{exc}；已完成 {max_rounds} 轮定向修复，仍有布局问题"
                    ) from exc
        if repaired_content is None:
            raise RuntimeError("定向布局修复没有产生译文")

        reading_html_path = None
        if export_reading_html:
            reading_html_path = self.run_phase_reading_d(structure, repaired_content)
        self._report_progress(
            "pipeline",
            3 if export_pdf else total_phases,
            total_phases,
        )

        pdf_path = self.run_phase_e(html_path) if export_pdf and html_path else None
        if export_pdf:
            self._report_progress("pipeline", total_phases, total_phases)

        result = self._build_result(
            structure,
            repaired_content,
            html_path,
            pdf_path,
            reading_html_path=reading_html_path,
        )
        self._write_report(result)
        return result

    def _load_layout_repair_groups(self) -> tuple[dict[str, dict], int]:
        """Read one current, compatible browser repair manifest strictly."""
        if not self._layout_repair_path.is_file():
            raise RuntimeError("没有可用的布局修复清单，请先完成一次布局检查")
        try:
            manifest = json.loads(self._layout_repair_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("布局修复清单无法读取，不能执行定向修复") from exc

        if manifest.get("schema_version") != 2:
            raise RuntimeError("布局修复清单版本不兼容，请重新执行布局检查")
        if manifest.get("profile_id") != self.config.profile_id:
            raise RuntimeError("布局修复清单的排版配置不匹配，请重新执行布局检查")
        unresolved = manifest.get("unresolved")
        if not isinstance(unresolved, list):
            raise RuntimeError("布局修复清单格式无效，不能执行定向修复")
        if unresolved:
            raise RuntimeError("存在无法定位到文字块的布局问题，不能自动修复")
        groups = manifest.get("groups")
        if not isinstance(groups, dict) or not groups:
            raise RuntimeError("布局修复清单没有可重译的文字块")

        repair_attempt = manifest.get("repair_attempt", 0)
        if not isinstance(repair_attempt, int) or repair_attempt < 0:
            raise RuntimeError("布局修复清单的重试次数无效")
        normalized: dict[str, dict] = {}
        for group_id, metadata in groups.items():
            if not isinstance(group_id, str) or not isinstance(metadata, dict):
                raise RuntimeError("布局修复清单包含无效目标")
            prompt = str(metadata.get("constraint_prompt", "")).strip()
            if repair_attempt:
                prompt += (
                    f"这是第 {repair_attempt + 1} 轮实测反馈修复；上一版仍未装入容器。"
                    "必须比上一版更紧凑，但不得删减事实、规则条件或数字。"
                )
            normalized[group_id] = {
                **metadata,
                "constraint_prompt": prompt,
                "repair_attempt": repair_attempt + 1,
            }
        return normalized, repair_attempt

    def run_phase_d(
        self,
        structure: PageStructureDocument,
        content: PageContentDocument,
    ) -> str:
        """Phase D: HTML/CSS rebuild.

        Rebuilds each page as HTML/CSS from the extracted structure and
        translated content.

        Args:
            structure: PageStructureDocument from Phase A.
            content: Translated PageContentDocument from Phase C.

        Returns:
            Path to the generated HTML file.
        """
        from exporters.typeset_html import TypesetHTMLRebuilder

        logger.info("Phase D: HTML 重建...")
        self._ensure_typeset_fonts()
        rebuilder = TypesetHTMLRebuilder(config=self.config)
        page_visuals = self._load_page_visuals_for_structure(structure)
        html_content = rebuilder.rebuild_document(
            structure,
            content,
            page_visuals=page_visuals,
        )

        # Validate a same-directory candidate so a failed rebuild cannot replace
        # the last known-good artifact and relative assets resolve identically.
        from exporters.typeset_pdf import TypesetPDFExporter

        from core.typeset_visibility import expected_render_blocks

        expected_blocks = expected_render_blocks(content, structure)
        with atomic_output_path(self._html_path) as candidate_path:
            candidate_path.write_text(html_content, encoding="utf-8")
            TypesetPDFExporter().validate_html_layout(
                str(candidate_path),
                report_path=str(self._layout_report_path),
                repair_manifest_path=str(self._layout_repair_path),
                profile_id=self.config.profile_id,
                repair_attempt=self._layout_repair_attempt,
                expected_blocks=expected_blocks,
                required_font_families=(
                    self.config.font_family,
                    self.config.heading_font_family,
                ),
            )
        self._mark_phase_completed("D")
        return str(self._html_path)

    def _ensure_typeset_fonts(self) -> None:
        """Copy the licensed embedded web fonts beside each HTML output."""
        source_dir = Path(__file__).resolve().parent.parent / "assets" / "typeset_fonts"
        required = (
            "fusion-fandol-song.woff2",
            "fusion-fandol-kai.woff2",
            "fusion-lanting-kanhei.woff2",
            "fusion-moushi-meili.woff2",
            "noto-serif-sc-400.woff2",
            "noto-serif-sc-700.woff2",
            "noto-sans-sc-400.woff2",
            "noto-sans-sc-700.woff2",
            "OFL-NOTO-SERIF-SC.txt",
            "OFL-NOTO-SANS-SC.txt",
        )
        missing = [name for name in required if not (source_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(f"高保真 HTML 字体资源缺失：{missing}")
        target_dir = self.output_dir / self.config.embedded_font_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in required:
            shutil.copy2(source_dir / name, target_dir / name)

    def run_phase_reading_d(
        self,
        structure: PageStructureDocument,
        content: PageContentDocument,
    ) -> str:
        """Phase D companion: responsive illustrated reading HTML."""
        from exporters.reading_html import ReadingHTMLRenderer

        logger.info("Phase D: 图文阅读 HTML 重建...")
        page_visuals = self._load_page_visuals_for_structure(structure)
        html_content = ReadingHTMLRenderer().rebuild_document(
            structure,
            content,
            page_visuals=page_visuals,
            fixed_html_href=self._html_path.name if self.config.reading_html_href else None,
        )
        with atomic_output_path(self._reading_html_path) as candidate_path:
            candidate_path.write_text(html_content, encoding="utf-8")
        return str(self._reading_html_path)

    def run_phase_e(self, html_path: str) -> str:
        """Phase E: PDF export.

        Renders the validated HTML to a candidate PDF and publishes it only
        after the resulting file contains at least one page.

        Args:
            html_path: Path to the typeset HTML file.

        Returns:
            Path to the generated PDF file.
        """
        from exporters.typeset_pdf import TypesetPDFExporter

        logger.info("Phase E: PDF 导出...")

        # Determine page dimensions from the HTML (use first page from structure)
        page_width_pt, page_height_pt = self._get_page_dimensions()

        exporter = TypesetPDFExporter()
        pdf_output = str(self._pdf_output_path)

        result = exporter.export_with_fallback(
            html_path=html_path,
            pdf_output=pdf_output,
            page_width_pt=page_width_pt,
            page_height_pt=page_height_pt,
        )
        if result.errors or result.failed_pages or result.success_pages <= 0:
            raise RuntimeError("PDF 导出未产生完整成品")
        self._mark_phase_completed("E")
        return pdf_output

    # ------------------------------------------------------------------
    # Checkpoint / Resume helpers
    # ------------------------------------------------------------------

    def _load_existing_structure(self) -> PageStructureDocument | None:
        """Load existing page_structure.json if valid."""
        if not self._page_structure_path.exists():
            return None
        try:
            text = self._page_structure_path.read_text(encoding="utf-8")
            doc = PageStructureDocument.from_json(text)
            # Verify schema version matches
            if doc.schema_version != PAGE_STRUCTURE_SCHEMA_VERSION:
                logger.warning(
                    "page_structure.json schema 版本不匹配，将重新提取"
                )
                return None
            if not self._matches_current_source(doc.source_pdf, doc.source_sha256):
                logger.warning(
                    "page_structure.json 来源 PDF 不匹配，将重新提取"
                )
                return None
            if not self._document_matches_requested_pages(doc):
                logger.warning(
                    "page_structure.json 页码范围不匹配，将重新提取"
                )
                return None
            if _has_browser_incompatible_images(doc, self.output_dir):
                logger.warning(
                    "page_structure.json 包含浏览器不支持的图片格式，将重新提取"
                )
                return None
            return doc
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning(f"page_structure.json 加载失败：{exc}")
            return None

    def _load_existing_content(self) -> PageContentDocument | None:
        """Load existing page_content.json if valid."""
        if (
            not self._page_content_path.exists()
            or not self._has_current_semantic_context()
        ):
            return None
        try:
            text = self._page_content_path.read_text(encoding="utf-8")
            doc = PageContentDocument.from_json(text)
            if doc.schema_version != PAGE_CONTENT_SCHEMA_VERSION:
                logger.warning(
                    "page_content.json schema 版本不匹配，将重新分析"
                )
                return None
            if not self._matches_current_source(doc.source_pdf, doc.source_sha256):
                logger.warning(
                    "page_content.json 来源 PDF 不匹配，将重新分析"
                )
                return None
            if not self._document_matches_requested_pages(doc):
                logger.warning(
                    "page_content.json 页码范围不匹配，将重新分析"
                )
                return None
            return doc
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning(f"page_content.json 加载失败：{exc}")
            return None

    def _normalize_image_overlay_blocks(
        self,
        content: PageContentDocument,
        structure: PageStructureDocument,
    ) -> PageContentDocument:
        """Exclude tiny text extracted from a foreground image overlay.

        A PDF may expose a checkbox letter or a form fragment as a text span
        even though the visible source is an image.  Such spans must stay in
        the authoritative visual layer, not become translated blocks.
        """
        structure_by_page = {page.page_index: page for page in structure.pages}
        from core.typeset_visibility import occluded_duplicate_block_ids

        changed = False
        pages = []
        for page in content.pages:
            page_structure = structure_by_page.get(page.page_index)
            if page_structure is None:
                pages.append(page)
                continue
            hidden_ids = occluded_duplicate_block_ids(page, page_structure)
            blocks = []
            for block in page.blocks:
                is_image_overlay = _is_image_overlay_text_block(
                    block, page_structure
                )
                if block.id not in hidden_ids and not is_image_overlay:
                    blocks.append(block)
                    continue
                changed = True
                blocks.append(
                    replace(
                        block,
                        translated_text=None,
                        translatable=False,
                        layout_mode=(
                            "hidden_source_text"
                            if block.id in hidden_ids
                            else "image_overlay_text"
                        ),
                    )
                )
            pages.append(replace(page, blocks=blocks))
        if not changed:
            return content
        return replace(content, pages=pages)

    def _load_existing_translated_content(
        self,
        allow_layout_hints: bool = False,
    ) -> PageContentDocument | None:
        """Load existing page_content_translated.json if valid.

        Only reuses if all translatable blocks have translations.
        """
        if not allow_layout_hints and self._resolve_layout_hints_path() is not None:
            return None
        if not self._page_content_translated_path.exists() or not self._has_current_translation_context():
            return None
        try:
            text = self._page_content_translated_path.read_text(encoding="utf-8")
            doc = PageContentDocument.from_json(text)
            if doc.schema_version != PAGE_CONTENT_SCHEMA_VERSION:
                return None
            if not self._matches_current_source(doc.source_pdf, doc.source_sha256):
                return None
            if not self._document_matches_requested_pages(doc):
                return None
            structure = self._load_existing_structure()
            if structure is not None:
                normalized = self._normalize_image_overlay_blocks(doc, structure)
                if normalized is not doc:
                    self._write_text_file(
                        self._page_content_translated_path,
                        normalized.to_json(),
                    )
                doc = normalized
            # Check if all translatable blocks have translations
            from core.translation_validation import contains_damaged_placeholder

            for page in doc.pages:
                for block in page.blocks:
                    if block.translatable and not block.translated_text:
                        # Incomplete translation, need to re-run
                        return None
                    if block.translatable and contains_damaged_placeholder(
                        block.translated_text or ""
                    ):
                        raise RuntimeError(
                            f"第 {page.page_index + 1} 页内容块 {block.id} 含 [damaged] 源文损坏占位符；"
                            "已保留现有译文，需修复该源块后定向重译，不能整本重翻。"
                        )
            return doc
        except (json.JSONDecodeError, ValueError, KeyError):
            return None

    def _mark_phase_completed(self, phase: str) -> None:
        """Mark a phase as completed in the progress file."""
        from core.typeset_translation import TypesetTranslationProgress

        progress = TypesetTranslationProgress(
            str(self._progress_path),
            context_signature=self._translation_context_signature(),
        )
        progress.mark_phase_completed(phase)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_page_visuals(
        self,
        structure: PageStructureDocument,
        *,
        force_rebuild: bool = False,
    ) -> None:
        """Create the authoritative clean SVG layer for every selected page."""
        if self._page_visuals_manifest_path.exists() and not force_rebuild:
            self._load_page_visuals_for_structure(structure)
            return

        from core.page_visuals import PageVisualExtractor

        logger.info("Phase A: 提取无原文文字的页面视觉层...")
        with PageVisualExtractor(self.pdf_path, self.output_dir) as extractor:
            pages = extractor.extract(
                start_page=self._start_page,
                end_page=self._end_page,
            )

        expected = {page.page_index + 1 for page in structure.pages}
        actual = {int(page["page"]) for page in pages}
        if actual != expected:
            raise ValueError(
                f"页面视觉资源范围不匹配：期望 {sorted(expected)}，实际 {sorted(actual)}"
            )
        source_sha256 = hashlib.sha256(Path(self.pdf_path).read_bytes()).hexdigest()
        manifest = {
            "schema_version": 1,
            "source_pdf": Path(self.pdf_path).name,
            "source_sha256": source_sha256,
            "pages": pages,
        }
        self._write_text_file(
            self._page_visuals_manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
        )
        self._load_page_visuals_for_structure(structure)

    def _load_page_visuals_for_structure(
        self,
        structure: PageStructureDocument,
    ) -> dict[int, str]:
        """Load and verify page-visual assets for a structure document."""
        if not self._page_visuals_manifest_path.exists():
            raise FileNotFoundError(f"页面视觉清单不存在：{self._page_visuals_manifest_path}")
        data = json.loads(self._page_visuals_manifest_path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            raise ValueError("页面视觉清单版本不兼容")

        structure_hash = getattr(structure, "source_sha256", None)
        manifest_hash = data.get("source_sha256")
        try:
            current_hash = self._current_source_sha256()
        except OSError as exc:
            raise FileNotFoundError(f"来源 PDF 不存在：{self.pdf_path}") from exc
        if (
            not structure_hash
            or manifest_hash != structure_hash
            or manifest_hash != current_hash
        ):
            raise ValueError("页面视觉清单来源 PDF 不匹配")

        expected = {page.page_index for page in structure.pages}
        result: dict[int, str] = {}
        for item in data.get("pages", []):
            page_index = int(item["page"]) - 1
            relative_path = str(item["svg"])
            output_root = self.output_dir.resolve()
            asset_path = (self.output_dir / relative_path).resolve()
            if asset_path != output_root and output_root not in asset_path.parents:
                raise ValueError(f"页面视觉资源路径越界：{relative_path}")
            if not asset_path.is_file():
                raise FileNotFoundError(f"页面视觉资源不存在：{asset_path}")
            digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
            if digest != item.get("sha256"):
                raise ValueError(f"页面视觉资源哈希不匹配：{asset_path}")
            if int(item.get("remaining_text_nodes", -1)) != 0:
                raise ValueError(f"页面视觉资源仍含原文文字：{asset_path}")
            if int(item.get("text_trace_count", -1)) != int(
                item.get("removed_text_nodes", -2)
            ):
                raise ValueError(f"页面视觉资源文字映射不完整：{asset_path}")
            if page_index in result:
                raise ValueError(f"页面视觉清单重复页：{page_index + 1}")
            result[page_index] = relative_path.replace("\\", "/")

        if set(result) != expected:
            missing = sorted(expected - set(result))
            extra = sorted(set(result) - expected)
            raise ValueError(
                f"页面视觉资源不完整：缺少 {missing}，多出 {extra}"
            )
        return result

    def _resolve_layout_hints_path(self) -> Path | None:
        """Return the configured or conventional layout hints path.

        The path is restricted to the project directory or the output directory.
        The pipeline reads and parses whatever it is given, so an unconstrained
        path turns a networked Streamlit instance into an arbitrary local-file
        reader and existence prober.
        """
        configured = self.config.layout_hints_path
        if configured:
            path = Path(configured).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"layout_hints 文件不存在：{path}")
            resolved = path.resolve()
            self._ensure_path_allowed(resolved)
            return resolved

        candidate = self.output_dir / "layout_hints.json"
        if candidate.exists():
            return candidate.resolve()
        return None

    def _ensure_path_allowed(self, path: Path) -> None:
        """Reject layout hints outside the project or output directory."""
        allowed_roots = [APP_DIR]
        try:
            allowed_roots.append(self.output_dir.resolve())
        except OSError:
            pass
        for root in allowed_roots:
            if path == root or root in path.parents:
                return
        allowed_text = "、".join(str(root) for root in allowed_roots)
        raise ValueError(
            f"layout_hints 路径超出允许范围：{path}。只能放在 {allowed_text} 之内。"
        )

    def _current_source_sha256(self) -> str:
        """Return the exact digest of the current source PDF."""
        if self._source_sha256_cache is None:
            self._source_sha256_cache = hashlib.sha256(
                Path(self.pdf_path).read_bytes()
            ).hexdigest()
        return self._source_sha256_cache

    def _source_page_count(self) -> int:
        if self._source_page_count_cache is not None:
            return self._source_page_count_cache
        try:
            try:
                import pymupdf
            except ImportError:
                import fitz as pymupdf
            with pymupdf.open(self.pdf_path) as document:
                count = len(document)
        except Exception as exc:
            raise RuntimeError(f"无法读取来源 PDF 页数：{self.pdf_path}") from exc
        if count <= 0:
            raise RuntimeError("来源 PDF 没有页面")
        self._source_page_count_cache = count
        return count

    def _expected_page_indexes(self) -> tuple[int, ...]:
        total = self._source_page_count()
        start = int(self._start_page)
        requested_end = total if self._end_page is None else int(self._end_page)
        if start < 0 or start >= total:
            raise ValueError(f"起始页超出范围：PDF 共 {total} 页")
        if requested_end <= start:
            raise ValueError("结束页必须大于起始页")
        end = min(requested_end, total)
        return tuple(range(start, end))

    def _document_matches_requested_pages(self, document) -> bool:
        actual = tuple(page.page_index for page in document.pages)
        expected = self._expected_page_indexes()
        return actual == expected and int(document.page_count) == len(expected)

    def _matches_current_source(self, source_pdf: str, source_sha256: str) -> bool:
        """Return whether an intermediate JSON belongs to this exact PDF."""
        if Path(source_pdf).name != Path(self.pdf_path).name or not source_sha256:
            return False
        try:
            return source_sha256 == self._current_source_sha256()
        except OSError:
            return False

    def _ensure_no_translation_failed(
        self,
        content: PageContentDocument,
        progress,
    ) -> None:
        translatable = [
            block
            for page in content.pages
            for block in page.blocks
            if block.translatable
        ]
        if not translatable:
            return
        missing = [block for block in translatable if not block.translated_text]
        if not missing:
            return

        sample_error = ""
        failed_blocks = getattr(progress, "failed_blocks", {}) or {}
        if failed_blocks:
            first_missing = missing[0].id
            sample_error = failed_blocks.get(first_missing) or next(iter(failed_blocks.values()))
        detail = f"；首个错误：{sample_error}" if sample_error else ""
        raise RuntimeError(
            f"图文重绘翻译未完成：{len(missing)}/{len(translatable)} 个区域失败{detail}"
        )

    def _get_page_dimensions(self) -> tuple[float, float]:
        """Get one verified page size for the selected source pages.

        Chromium exports one size for the whole output. Mixed-size selections
        therefore fail explicitly instead of being silently forced to Letter.
        """
        try:
            try:
                import pymupdf
            except ImportError:
                import fitz as pymupdf
            indexes = self._expected_page_indexes()
            with pymupdf.open(self.pdf_path) as document:
                dimensions = {
                    (
                        round(float(document[index].rect.width), 3),
                        round(float(document[index].rect.height), 3),
                    )
                    for index in indexes
                }
        except Exception as exc:
            raise RuntimeError("无法读取来源 PDF 页面尺寸") from exc
        if len(dimensions) != 1:
            raise RuntimeError(
                "所选页面尺寸不一致，固定页 PDF 不能用一个页面尺寸导出"
            )
        return next(iter(dimensions))

    def _build_result(
        self,
        structure: PageStructureDocument,
        content: PageContentDocument,
        html_path: str | None,
        pdf_path: str | None,
        reading_html_path: str | None = None,
    ) -> TypesetResult:
        """Build the final TypesetResult from pipeline outputs."""
        translated_regions = 0
        failed_regions = 0

        for page in content.pages:
            for block in page.blocks:
                if block.translatable:
                    if block.translated_text:
                        translated_regions += 1
                    else:
                        failed_regions += 1

        stats = getattr(self.translator, "stats", None)
        return TypesetResult(
            pdf_path=pdf_path,
            html_path=html_path,
            reading_html_path=reading_html_path,
            page_structure_path=str(self._page_structure_path),
            page_content_path=str(self._page_content_path),
            total_pages=structure.page_count,
            translated_regions=translated_regions,
            failed_regions=failed_regions,
            export_errors=list(self._errors),
            input_tokens=int(getattr(stats, "input_tokens", 0) or 0),
            output_tokens=int(getattr(stats, "output_tokens", 0) or 0),
            cached_tokens=int(getattr(stats, "cached_tokens", 0) or 0),
            total_tokens=int(getattr(stats, "total_tokens", 0) or 0),
            api_calls=int(getattr(stats, "api_calls", 0) or 0),
            failed_calls=int(getattr(stats, "failed_calls", 0) or 0),
            translation_cache_hits=int(
                getattr(stats, "translation_cache_hits", 0) or 0
            ),
            cost_usd=getattr(stats, "cost_usd", None),
            layout_report_path=str(self._layout_report_path)
            if self._layout_report_path.exists()
            else None,
            layout_repair_path=str(self._layout_repair_path)
            if self._layout_repair_path.exists()
            else None,
            quality_report_path=str(self._quality_report_path)
            if self._quality_report_path.exists()
            else None,
        )

    def _write_report(self, result: TypesetResult) -> None:
        """Write _typeset_report.json with per-page status and errors."""
        report = {
            "pipeline": "typeset",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source_pdf": Path(self.pdf_path).name,
            "total_pages": result.total_pages,
            "translated_regions": result.translated_regions,
            "failed_regions": result.failed_regions,
            "pdf_output": _report_file_name(result.pdf_path),
            "html_output": _report_file_name(result.html_path),
            "reading_html_output": _report_file_name(result.reading_html_path),
            "layout_report": _report_file_name(result.layout_report_path),
            "layout_repair": _report_file_name(result.layout_repair_path),
            "quality_report": _report_file_name(result.quality_report_path),
            "errors": result.export_errors,
            "usage": {
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cached_tokens": result.cached_tokens,
                "total_tokens": result.total_tokens,
                "api_calls": result.api_calls,
                "failed_calls": result.failed_calls,
                "translation_cache_hits": result.translation_cache_hits,
                "cost_usd": result.cost_usd,
            },
            "config": {
                "profile_id": self.config.profile_id,
                "source_language": self.config.source_language,
                "font_family": self.config.font_family,
                "fallback_fonts": self.config.fallback_fonts,
                "body_font_size_pt": self.config.body_font_size_pt,
                "line_height": self.config.line_height,
                "layout_hints_path": _report_file_name(self.config.layout_hints_path),
            },
        }
        self._write_text_file(
            self._report_path,
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )

    def _report_progress(self, phase: str, done: int, total: int) -> None:
        """Report progress via callback if available."""
        if self._progress_callback:
            self._progress_callback(phase, done, total)


def _has_browser_incompatible_images(
    doc: PageStructureDocument,
    output_dir: Path | None = None,
) -> bool:
    """Return True when cached image assets cannot be rendered by Chromium."""
    unsupported = {".jpx", ".jp2", ".j2k", ".jpf"}
    for page in doc.pages:
        previous_images = []
        for image in page.images:
            if Path(image.image_path).suffix.lower() in unsupported:
                return True
            if (
                output_dir is not None
                and _is_cached_dark_full_page_overlay(page, image, previous_images, output_dir)
            ):
                return True
            previous_images.append(image)
    return False


def _is_cached_dark_full_page_overlay(page, image, previous_images, output_dir: Path) -> bool:
    if not page.text_regions:
        return False
    if not _cached_bbox_covers_page(image.bbox, page.width, page.height):
        return False
    if not any(
        _cached_bbox_covers_page(previous.bbox, page.width, page.height)
        for previous in previous_images
    ):
        return False

    image_path = Path(image.image_path)
    if not image_path.is_absolute():
        image_path = output_dir / image_path
    if not image_path.exists():
        return False

    from PIL import Image

    with Image.open(image_path) as loaded:
        return _is_cached_mostly_dark_opaque_image(loaded)


def _cached_bbox_covers_page(
    bbox: list[float],
    page_width: float,
    page_height: float,
) -> bool:
    if len(bbox) != 4:
        return False
    x0, y0, x1, y1 = [float(v) for v in bbox]
    width = max(0.0, x1 - x0)
    height = max(0.0, y1 - y0)
    return width >= page_width * 0.9 and height >= page_height * 0.9


def _is_cached_mostly_dark_opaque_image(image) -> bool:
    from PIL import ImageChops

    rgba = image.convert("RGBA")
    total = max(1, rgba.width * rgba.height)
    alpha = rgba.getchannel("A")
    lightness = rgba.convert("L")
    opaque_mask = alpha.point(lambda value: 255 if value >= 250 else 0)
    dark_mask = lightness.point(lambda value: 255 if value <= 24 else 0)
    dark_opaque_mask = ImageChops.multiply(opaque_mask, dark_mask)
    opaque = opaque_mask.histogram()[255]
    dark = dark_opaque_mask.histogram()[255]
    return opaque / total >= 0.9 and dark / total >= 0.85
