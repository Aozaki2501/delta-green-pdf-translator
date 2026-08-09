"""
Typeset PDF exporter using Playwright headless Chromium.

Renders the typeset HTML (produced by TypesetHTMLRebuilder) into a
professional-quality PDF with correct page dimensions and embedded fonts.
Uses Playwright headless Chromium for PDF generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

from core.utils import atomic_output_path, ensure_output_parent


@dataclass
class ExportResult:
    """PDF export result with page-level status tracking."""

    success_pages: int = 0
    failed_pages: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    layout_issues: list[dict] = field(default_factory=list)


def _file_url(path: str) -> str:
    """Convert a local file path to a file:// URL."""
    return Path(path).resolve().as_uri()


def write_layout_report(issues: list[dict], output_path: str) -> None:
    """Write the complete browser layout findings as deterministic JSON."""
    ensure_output_parent(output_path)
    normalized = TypesetPDFExporter._normalize_layout_issues(issues)
    with atomic_output_path(output_path) as candidate:
        candidate.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )


def write_layout_repair_manifest(
    issues: list[dict],
    output_path: str,
    *,
    profile_id: str = "delta_green",
    repair_attempt: int = 0,
) -> None:
    """Write measured target constraints for reviewed, shared-container retries.

    The manifest deliberately contains browser measurements instead of a
    guessed character budget.  Callers pass its ``groups`` mapping to
    ``TypesetPipeline.repair_overflow_translations`` after reviewing the
    affected blocks.
    """
    if not isinstance(repair_attempt, int) or repair_attempt < 0:
        raise ValueError("repair_attempt 必须是非负整数")
    normalized = TypesetPDFExporter._normalize_layout_issues(issues)
    groups: dict[str, dict] = {}
    unresolved: list[dict] = []
    owners: dict[str, str] = {}
    for issue in normalized:
        block_ids = issue.get("block_ids") or []
        if not isinstance(block_ids, list) or not block_ids:
            unresolved.append({
                "page": issue.get("page", ""),
                "target": issue.get("target") or issue.get("id", ""),
                "kind": issue.get("kind", ""),
            })
            continue
        block_ids = [str(block_id) for block_id in block_ids]
        overlapping = sorted(block_id for block_id in block_ids if block_id in owners)
        if overlapping:
            unresolved.append({
                "page": issue.get("page", ""),
                "target": issue.get("target") or issue.get("id", ""),
                "kind": issue.get("kind", ""),
                "reason": "overlapping_blocks:" + ",".join(overlapping),
            })
            continue
        capacity = {
            "bbox": issue.get("bbox") or {},
            "client_width": issue.get("client_width"),
            "client_height": issue.get("client_height"),
            "scroll_width": issue.get("scroll_width"),
            "scroll_height": issue.get("scroll_height"),
            "overflow_x": issue.get("overflow_x", 0),
            "overflow_y": issue.get("overflow_y", 0),
            "page_boundary_overflow": issue.get("page_boundary_overflow") or {},
        }
        template_payload = {
            "profile_id": profile_id,
            "kind": issue.get("kind", ""),
            "target": issue.get("target") or issue.get("id", ""),
            "bbox": capacity["bbox"],
        }
        template_signature = hashlib.sha256(
            json.dumps(
                template_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        constraint_prompt = (
            "把这一组全部 BLOCK 视为同一个连续容器，完整保留原文信息、规则术语和数字；"
            "所有 BLOCK 的译文合计必须在已测得的目标模板中自然改写，"
            f"目标类型为 {issue.get('kind', 'layout target')}，"
            f"可用尺寸为 {capacity['client_width']}x{capacity['client_height']}px，"
            f"当前垂直溢出为 {capacity['overflow_y']}px。"
            "保留每个 BLOCK 标记，不要输出解释，不要删去规则条件。"
        )
        group_payload = {
            "page": issue.get("page", ""),
            "kind": issue.get("kind", ""),
            "target": issue.get("target") or issue.get("id", ""),
            "block_ids": block_ids,
        }
        group_id = "group_" + hashlib.sha256(
            json.dumps(group_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        groups[group_id] = {
            "block_ids": block_ids,
            "capacity": capacity,
            "template_signature": template_signature,
            "constraint_prompt": constraint_prompt,
            "page": issue.get("page", ""),
            "target_id": issue.get("target") or issue.get("id", ""),
            "kind": issue.get("kind", ""),
        }
        for block_id in block_ids:
            owners[block_id] = group_id
    manifest = {
        "schema_version": 2,
        "profile_id": profile_id,
        "repair_attempt": repair_attempt,
        "groups": groups,
        "unresolved": unresolved,
    }
    ensure_output_parent(output_path)
    with atomic_output_path(output_path) as candidate:
        candidate.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )


class TypesetPDFExporter:
    """
    Typeset PDF exporter.

    Uses Playwright headless Chromium to render the typeset HTML into PDF.
    Page dimensions are specified in PDF points and converted to inches
    for the Playwright PDF API (divide by 72).
    """

    def validate_html_layout(
        self,
        html_path: str,
        *,
        report_path: str | None = None,
        repair_manifest_path: str | None = None,
        profile_id: str = "delta_green",
        repair_attempt: int = 0,
        expected_blocks: Mapping[str, str] | None = None,
        required_font_families: Sequence[str] = (),
    ) -> list[dict]:
        """Fail HTML-only output on layout, content ownership, or asset defects."""
        if not Path(html_path).exists():
            raise FileNotFoundError(f"HTML 文件不存在：{html_path}")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "缺少 playwright。请先运行：pip install playwright && playwright install chromium"
            ) from exc

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(_file_url(html_path), wait_until="networkidle")
                self._wait_for_render_assets(page)
                issues = self._fit_and_collect_layout_issues(page)
                ownership_issues = self._collect_content_ownership_issues(
                    page, expected_blocks or {}
                )
                asset_issues = self._collect_asset_issues(
                    page, required_font_families
                )
                if report_path:
                    write_layout_report(issues, report_path)
                if repair_manifest_path:
                    write_layout_repair_manifest(
                        issues,
                        repair_manifest_path,
                        profile_id=profile_id,
                        repair_attempt=repair_attempt,
                    )
                self._raise_for_asset_issues(asset_issues)
                self._raise_for_content_ownership_issues(ownership_issues)
                self._raise_for_layout_issues(issues)
                return issues
            finally:
                browser.close()

    def export(
        self,
        html_path: str,
        pdf_output: str,
        page_width_pt: float,
        page_height_pt: float,
    ) -> ExportResult:
        """
        Render the full typeset HTML to PDF using Playwright.

        Args:
            html_path: Path to the typeset HTML file.
            pdf_output: Output PDF file path (should end with _typeset.pdf).
            page_width_pt: Page width in PDF points.
            page_height_pt: Page height in PDF points.

        Returns:
            ExportResult with success/failure information.

        Raises:
            FileNotFoundError: If html_path does not exist.
            ValueError: If page dimensions are invalid.
            RuntimeError: If Playwright is not installed.
        """
        if not Path(html_path).exists():
            raise FileNotFoundError(f"HTML 文件不存在：{html_path}")
        if page_width_pt <= 0 or page_height_pt <= 0:
            raise ValueError("PDF 页面尺寸无效")
        ensure_output_parent(pdf_output)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "缺少 playwright。请先运行：pip install playwright && playwright install chromium"
            ) from exc

        result = ExportResult()
        with atomic_output_path(pdf_output) as candidate_path:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                try:
                    page = browser.new_page()
                    page.goto(_file_url(html_path), wait_until="networkidle")
                    self._wait_for_render_assets(page)
                    result.layout_issues = self._fit_and_collect_layout_issues(page)
                    self._raise_for_layout_issues(result.layout_issues)
                    page.pdf(
                        path=str(candidate_path),
                        width=f"{page_width_pt / 72.0}in",
                        height=f"{page_height_pt / 72.0}in",
                        margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                        print_background=True,
                        prefer_css_page_size=True,
                    )
                finally:
                    browser.close()

            result.success_pages = self._count_pdf_pages(str(candidate_path))
            if result.success_pages <= 0:
                raise RuntimeError("PDF 导出结果没有页面")
        return result

    def export_with_fallback(
        self,
        html_path: str,
        pdf_output: str,
        page_width_pt: float,
        page_height_pt: float,
    ) -> ExportResult:
        """Backward-compatible strict alias for :meth:`export`."""
        return self.export(
            html_path=html_path,
            pdf_output=pdf_output,
            page_width_pt=page_width_pt,
            page_height_pt=page_height_pt,
        )

    def _wait_for_render_assets(self, page) -> None:
        """Wait until fonts, SVG/image decoding and paint frames are complete."""
        page.evaluate("""async () => {
            if (document.fonts) await document.fonts.ready;
            await Promise.all(Array.from(document.images).map(async (image) => {
                if (!image.complete) {
                    await new Promise((resolve, reject) => {
                        image.addEventListener('load', resolve, {once: true});
                        image.addEventListener('error', reject, {once: true});
                    });
                }
                if (image.decode) await image.decode();
            }));
            await new Promise((resolve) => {
                requestAnimationFrame(() => requestAnimationFrame(resolve));
            });
        }""")

    def _fit_and_collect_layout_issues(self, page) -> list[dict]:
        page.evaluate(
            "window.typesetFitPositionedBlocks ? window.typesetFitPositionedBlocks() : undefined"
        )
        issues = page.evaluate(
            r"""() => {
                const collected = window.typesetCollectLayoutIssues
                    ? window.typesetCollectLayoutIssues()
                    : [];
                if (!Array.isArray(collected)) return [];
                const elements = Array.from(document.querySelectorAll(
                    '[data-fit="text"], [data-fit="reflow"], [data-fit="table"], .typeset-line-track-flow'
                )).map((el) => {
                    const page = el.closest('.typeset-page');
                    const pageRect = page ? page.getBoundingClientRect() : null;
                    const rect = el.getBoundingClientRect();
                    const kind = typeof el.className === 'string' && el.className
                        ? el.className
                        : el.tagName;
                    const id = el.dataset.regionId || el.dataset.flowBlocks ||
                        el.dataset.tableBlock || el.dataset.column || '';
                    const blockId = el.dataset.blockId || '';
                    const target = blockId || id;
                    const explicitBlockIds = String(el.dataset.flowBlocks || '')
                        .split(/[,\s]+/).map((item) => item.trim()).filter(Boolean);
                    const blockIds = explicitBlockIds.length
                        ? explicitBlockIds
                        : Array.from(el.querySelectorAll('[data-block-id]'))
                            .map((child) => child.dataset.blockId || '')
                            .filter(Boolean);
                    if (blockId && !blockIds.includes(blockId)) blockIds.unshift(blockId);
                    const boundary = pageRect ? {
                        left: Math.max(0, pageRect.left - rect.left),
                        top: Math.max(0, pageRect.top - rect.top),
                        right: Math.max(0, rect.right - pageRect.right),
                        bottom: Math.max(0, rect.bottom - pageRect.bottom),
                    } : {left: 0, top: 0, right: 0, bottom: 0};
                    return {
                        page: page ? page.dataset.page || '' : '',
                        kind,
                        id,
                        target,
                        target_id: target,
                        block_ids: blockIds,
                        block_id: blockId,
                        region_id: el.dataset.regionId || '',
                        flow_blocks: el.dataset.flowBlocks || '',
                        table_block: el.dataset.tableBlock || '',
                        column: el.dataset.column || '',
                        bbox: {
                            x: pageRect ? rect.left - pageRect.left : rect.left,
                            y: pageRect ? rect.top - pageRect.top : rect.top,
                            width: rect.width,
                            height: rect.height,
                        },
                        page_boundary_overflow: boundary,
                        client_width: el.clientWidth,
                        client_height: el.clientHeight,
                        scroll_width: el.scrollWidth,
                        scroll_height: el.scrollHeight,
                        overflow_x: Math.max(0, el.scrollWidth - el.clientWidth),
                        overflow_y: Math.max(0, el.scrollHeight - el.clientHeight),
                    };
                });
                const remaining = [...elements];
                return collected.map((issue) => {
                    const candidateIndexes = remaining
                        .map((element, index) => ({element, index}))
                        .filter(({element}) =>
                            String(element.page) === String(issue.page || '') &&
                            element.kind === (issue.kind || '') &&
                            element.id === (issue.id || '')
                        );
                    const overflowing = candidateIndexes.find(({element}) =>
                        element.overflow_x > 0 || element.overflow_y > 0 ||
                        Object.values(element.page_boundary_overflow || {}).some((value) => value > 4)
                    );
                    const matchIndex = overflowing
                        ? overflowing.index
                        : (candidateIndexes[0] ? candidateIndexes[0].index : -1);
                    const match = matchIndex >= 0 ? remaining.splice(matchIndex, 1)[0] : null;
                    return match ? {...issue, ...match} : issue;
                });
            }"""
        )
        return self._normalize_layout_issues(issues if isinstance(issues, list) else [])

    def _collect_content_ownership_issues(
        self,
        page,
        expected_blocks: Mapping[str, str],
    ) -> list[dict]:
        if not expected_blocks:
            return []
        return page.evaluate(
            r"""(expected) => {
                const owners = new Map();
                const pageNumber = (element) =>
                    element.closest('.typeset-page')?.dataset.page || '';
                const addOwner = (blockId, element, kind) => {
                    if (!blockId) return;
                    const values = owners.get(blockId) || [];
                    values.push({
                        page: pageNumber(element),
                        owner: element.dataset.regionId ||
                            element.dataset.flowBlocks || blockId,
                        kind,
                    });
                    owners.set(blockId, values);
                };
                for (const flow of document.querySelectorAll('[data-flow-blocks]')) {
                    const ids = String(flow.dataset.flowBlocks || '')
                        .split(/[,\s]+/).map((item) => item.trim()).filter(Boolean);
                    for (const blockId of ids) addOwner(blockId, flow, 'flow');
                }
                for (const element of document.querySelectorAll('[data-block-id]')) {
                    if (element.closest('[data-flow-blocks]')) continue;
                    addOwner(element.dataset.blockId || '', element, 'element');
                }

                const issues = [];
                for (const [blockId, expectedPage] of Object.entries(expected)) {
                    const values = owners.get(blockId) || [];
                    if (values.length === 0) {
                        issues.push({block_id: blockId, page: expectedPage, reason: 'missing'});
                        continue;
                    }
                    if (values.length !== 1) {
                        issues.push({
                            block_id: blockId,
                            page: expectedPage,
                            reason: 'multiple_owners',
                            owners: values,
                        });
                        continue;
                    }
                    if (String(values[0].page) !== String(expectedPage)) {
                        issues.push({
                            block_id: blockId,
                            page: expectedPage,
                            reason: 'wrong_page',
                            owners: values,
                        });
                    }
                }
                return issues;
            }""",
            dict(expected_blocks),
        )

    def _collect_asset_issues(
        self,
        page,
        required_font_families: Sequence[str],
    ) -> list[dict]:
        return page.evaluate(
            """(families) => {
                const issues = [];
                for (const image of document.images) {
                    if (!image.complete || image.naturalWidth === 0) {
                        issues.push({kind: 'image', target: image.getAttribute('src') || ''});
                    }
                }
                if (!document.fonts || document.fonts.status !== 'loaded') {
                    issues.push({kind: 'font-set', target: document.fonts?.status || 'unsupported'});
                    return issues;
                }
                for (const family of families) {
                    const fontSpec = `normal 400 16px ${JSON.stringify(String(family))}`;
                    if (!document.fonts.check(fontSpec, '汉字Aa')) {
                        issues.push({kind: 'font', target: String(family)});
                    }
                }
                return issues;
            }""",
            [str(family) for family in required_font_families if str(family).strip()],
        )

    @staticmethod
    def _raise_for_content_ownership_issues(issues: list[dict]) -> None:
        if not issues:
            return
        preview = "; ".join(
            f"page={issue.get('page', '?')} block={issue.get('block_id', '')} "
            f"reason={issue.get('reason', '')}"
            for issue in issues[:10]
        )
        suffix = f"; ...(+{len(issues) - 10})" if len(issues) > 10 else ""
        raise RuntimeError(
            f"typeset content ownership: {len(issues)} issue(s); {preview}{suffix}"
        )

    @staticmethod
    def _raise_for_asset_issues(issues: list[dict]) -> None:
        if not issues:
            return
        preview = "; ".join(
            f"kind={issue.get('kind', '')} target={issue.get('target', '')}"
            for issue in issues[:10]
        )
        suffix = f"; ...(+{len(issues) - 10})" if len(issues) > 10 else ""
        raise RuntimeError(
            f"typeset render assets: {len(issues)} issue(s); {preview}{suffix}"
        )

    @staticmethod
    def _normalize_layout_issues(issues: list[dict]) -> list[dict]:
        """Sort browser findings so reports and errors are reproducible."""
        normalized = [dict(issue) for issue in issues if isinstance(issue, dict)]

        def sort_key(issue: dict) -> tuple:
            page = str(issue.get("page") or "")
            page_key = (0, int(page)) if page.isdigit() else (1, page)
            return page_key + tuple(str(issue.get(key) or "") for key in (
                "target", "block_id", "region_id", "id", "kind",
            ))

        return sorted(
            normalized,
            key=sort_key,
        )

    def _raise_for_layout_issues(self, issues: list[dict]) -> None:
        if not issues:
            return
        details: list[str] = []
        for issue in self._normalize_layout_issues(issues):
            page = issue.get("page") or "?"
            kind = issue.get("kind") or "unknown"
            item_id = issue.get("id") or ""
            target = issue.get("target") or item_id
            identifiers = [f"page={page}", f"kind={kind}"]
            if target:
                identifiers.append(f"target={target}")
            if item_id and item_id != target:
                identifiers.append(f"id={item_id}")
            for field, label in (
                ("block_id", "block"),
                ("region_id", "region"),
                ("flow_blocks", "blocks"),
                ("table_block", "table"),
                ("column", "column"),
            ):
                value = issue.get(field)
                if value and value != target and value != item_id:
                    identifiers.append(f"{label}={value}")
            block_ids = issue.get("block_ids") or []
            if isinstance(block_ids, list) and block_ids:
                preview = ",".join(str(value) for value in block_ids[:3])
                suffix = f"...(+{len(block_ids) - 3})" if len(block_ids) > 3 else ""
                identifiers.append(f"block_ids={preview}{suffix}")
            dimensions = (
                "client_width", "client_height", "scroll_width", "scroll_height",
            )
            if all(value is not None for value in (issue.get(field) for field in dimensions)):
                identifiers.append(
                    "client="
                    f"{issue['client_width']}x{issue['client_height']} "
                    "scroll="
                    f"{issue['scroll_width']}x{issue['scroll_height']}"
                )
            if issue.get("overflow_x") is not None or issue.get("overflow_y") is not None:
                identifiers.append(
                    f"overflow={issue.get('overflow_x', 0)}x{issue.get('overflow_y', 0)}"
                )
            boundary = issue.get("page_boundary_overflow") or {}
            if any(float(boundary.get(side, 0) or 0) > 4 for side in ("left", "top", "right", "bottom")):
                identifiers.append(
                    "page-boundary="
                    + ",".join(
                        f"{side}:{float(boundary.get(side, 0) or 0):.1f}"
                        for side in ("left", "top", "right", "bottom")
                        if float(boundary.get(side, 0) or 0) > 4
                    )
                )
            details.append(" ".join(identifiers))
        raise RuntimeError(
            "typeset layout overflow: "
            f"{len(issues)} issue(s); "
            + "; ".join(details)
        )

    @staticmethod
    def _count_pdf_pages(pdf_path: str) -> int:
        """Count pages in a PDF file using PyMuPDF."""
        try:
            import pymupdf
        except ImportError:
            import fitz as pymupdf
        with pymupdf.open(pdf_path) as document:
            return len(document)
