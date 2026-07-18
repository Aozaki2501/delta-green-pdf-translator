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

import hashlib
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Callable

from core.typeset_models import (
    PAGE_CONTENT_SCHEMA_VERSION,
    PAGE_STRUCTURE_SCHEMA_VERSION,
    PageContentDocument,
    PageStructureDocument,
    TypesetConfig,
    TypesetResult,
)

logger = logging.getLogger(__name__)


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
        self.glossary = glossary or {}
        self.config = config or TypesetConfig()
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
        self._report_path = (
            self.output_dir / f"{self._pdf_stem}_typeset_report.json"
        )

        # Pipeline state
        self._start_page: int = 0
        self._end_page: int | None = None
        self._progress_callback: Callable | None = None
        self._errors: list[str] = []
        self._source_sha256_cache: str | None = None

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
        self._page_structure_path.write_text(
            structure.to_json(), encoding="utf-8"
        )
        self._ensure_page_visuals(structure)
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
            logger.info("Phase B: 复用已有 page_content.json")
            return existing

        from core.semantic_analyzer import SemanticAnalyzer

        logger.info("Phase B: 语义化分析...")
        with SemanticAnalyzer(self.pdf_path, str(self.output_dir)) as analyzer:
            content = analyzer.analyze_document(structure)

        # Save to file
        self._page_content_path.write_text(
            content.to_json(), encoding="utf-8"
        )
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
        self._page_content_hinted_path.write_text(
            hinted.to_json(), encoding="utf-8"
        )
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
            return existing

        logger.info("Phase C: 翻译...")

        # Load or create progress file
        progress = TypesetTranslationProgress(str(self._progress_path))

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
        )
        self._ensure_no_translation_failed(translated, progress)

        # Save translated content
        save_translated_content(
            translated, str(self._page_content_translated_path)
        )
        self._mark_phase_completed("C")
        return translated

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

        # Save HTML file
        self._html_path.parent.mkdir(parents=True, exist_ok=True)
        self._html_path.write_text(html_content, encoding="utf-8")
        self._mark_phase_completed("D")
        return str(self._html_path)

    def _ensure_typeset_fonts(self) -> None:
        """Copy the licensed embedded web fonts beside each HTML output."""
        source_dir = Path(__file__).resolve().parent.parent / "assets" / "typeset_fonts"
        required = (
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
        )
        self._reading_html_path.parent.mkdir(parents=True, exist_ok=True)
        self._reading_html_path.write_text(html_content, encoding="utf-8")
        return str(self._reading_html_path)

    def run_phase_e(self, html_path: str) -> str | None:
        """Phase E: PDF export.

        Renders the HTML to PDF using Playwright. If Playwright is not
        available or export fails, records the error and returns None.

        Args:
            html_path: Path to the typeset HTML file.

        Returns:
            Path to the generated PDF file, or None if export failed.
        """
        from exporters.typeset_pdf import TypesetPDFExporter

        logger.info("Phase E: PDF 导出...")

        # Determine page dimensions from the HTML (use first page from structure)
        page_width_pt, page_height_pt = self._get_page_dimensions()

        exporter = TypesetPDFExporter()
        pdf_output = str(self._pdf_output_path)

        try:
            result = exporter.export_with_fallback(
                html_path=html_path,
                pdf_output=pdf_output,
                page_width_pt=page_width_pt,
                page_height_pt=page_height_pt,
            )
            if result.errors:
                self._errors.extend(result.errors)
            if result.failed_pages:
                for page_num in result.failed_pages:
                    self._errors.append(f"PDF 导出第 {page_num} 页失败")
            if result.errors or result.failed_pages or result.success_pages <= 0:
                return None
            self._mark_phase_completed("E")
            return pdf_output
        except RuntimeError as exc:
            # Playwright not installed or other critical error
            error_msg = f"PDF 导出失败：{exc}"
            self._errors.append(error_msg)
            logger.error(error_msg)
            return None
        except (FileNotFoundError, ValueError) as exc:
            error_msg = f"PDF 导出失败：{exc}"
            self._errors.append(error_msg)
            logger.error(error_msg)
            return None

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
        if not self._page_content_path.exists():
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
            return doc
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning(f"page_content.json 加载失败：{exc}")
            return None

    def _load_existing_translated_content(self) -> PageContentDocument | None:
        """Load existing page_content_translated.json if valid.

        Only reuses if all translatable blocks have translations.
        """
        if self._resolve_layout_hints_path() is not None:
            return None
        if not self._page_content_translated_path.exists():
            return None
        try:
            text = self._page_content_translated_path.read_text(encoding="utf-8")
            doc = PageContentDocument.from_json(text)
            if doc.schema_version != PAGE_CONTENT_SCHEMA_VERSION:
                return None
            if not self._matches_current_source(doc.source_pdf, doc.source_sha256):
                return None
            # Check if all translatable blocks have translations
            for page in doc.pages:
                for block in page.blocks:
                    if block.translatable and not block.translated_text:
                        # Incomplete translation, need to re-run
                        return None
            return doc
        except (json.JSONDecodeError, ValueError, KeyError):
            return None

    def _mark_phase_completed(self, phase: str) -> None:
        """Mark a phase as completed in the progress file."""
        from core.typeset_translation import TypesetTranslationProgress

        try:
            progress = TypesetTranslationProgress(str(self._progress_path))
            progress.mark_phase_completed(phase)
        except Exception:
            pass  # Non-critical

    def _is_phase_completed(self, phase: str) -> bool:
        """Check if a phase has been completed."""
        from core.typeset_translation import TypesetTranslationProgress

        try:
            progress = TypesetTranslationProgress(str(self._progress_path))
            return progress.is_phase_completed(phase)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_page_visuals(self, structure: PageStructureDocument) -> None:
        """Create the authoritative clean SVG layer for every selected page."""
        if self._page_visuals_manifest_path.exists():
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
        self._page_visuals_manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
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
        """Return the configured or conventional layout hints path."""
        configured = self.config.layout_hints_path
        if configured:
            path = Path(configured).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"layout_hints 文件不存在：{path}")
            return path.resolve()

        candidate = self.output_dir / "layout_hints.json"
        if candidate.exists():
            return candidate.resolve()
        return None

    def _current_source_sha256(self) -> str:
        """Return the exact digest of the current source PDF."""
        if self._source_sha256_cache is None:
            self._source_sha256_cache = hashlib.sha256(
                Path(self.pdf_path).read_bytes()
            ).hexdigest()
        return self._source_sha256_cache

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
        """Get page dimensions from the source PDF (first page).

        Returns:
            (width_pt, height_pt) tuple.
        """
        try:
            try:
                import pymupdf
            except ImportError:
                import fitz as pymupdf

            doc = pymupdf.open(self.pdf_path)
            if len(doc) > 0:
                page = doc[0]
                width = float(page.rect.width)
                height = float(page.rect.height)
                doc.close()
                return width, height
            doc.close()
        except Exception:
            pass
        # Default to US Letter if PDF cannot be read
        return 612.0, 792.0

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
            cost_yuan=float(getattr(stats, "cost_yuan", 0.0) or 0.0),
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
            "pdf_output": result.pdf_path,
            "html_output": result.html_path,
            "reading_html_output": result.reading_html_path,
            "errors": result.export_errors,
            "usage": {
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cached_tokens": result.cached_tokens,
                "total_tokens": result.total_tokens,
                "api_calls": result.api_calls,
                "failed_calls": result.failed_calls,
                "translation_cache_hits": result.translation_cache_hits,
                "cost_yuan": result.cost_yuan,
            },
            "config": {
                "font_family": self.config.font_family,
                "fallback_fonts": self.config.fallback_fonts,
                "body_font_size_pt": self.config.body_font_size_pt,
                "line_height": self.config.line_height,
                "layout_hints_path": self.config.layout_hints_path,
            },
        }
        try:
            self._report_path.parent.mkdir(parents=True, exist_ok=True)
            self._report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning(f"无法写入报告文件：{exc}")

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
