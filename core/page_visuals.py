"""Generate text-free SVG page visuals from a PDF.

PyMuPDF can render a PDF page as SVG while keeping images and vector drawing
commands intact.  This module removes only SVG ``text`` elements using an XML
parser; it deliberately does not use regular expressions, OCR, or a raster
fallback.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    import pymupdf
except ImportError:  # pragma: no cover - compatibility with older installs
    try:
        import fitz as pymupdf
    except ImportError as exc:  # pragma: no cover
        raise ImportError("PyMuPDF not installed. Run: pip install pymupdf") from exc


SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
INKSCAPE_NAMESPACE = "http://www.inkscape.org/namespaces/inkscape"

# Keep the output readable and deterministic rather than letting ElementTree
# invent ns0/ns1 prefixes during serialization.
ET.register_namespace("", SVG_NAMESPACE)
ET.register_namespace("xlink", XLINK_NAMESPACE)
ET.register_namespace("inkscape", INKSCAPE_NAMESPACE)


def _local_name(tag: Any) -> str:
    """Return an XML tag's local name, independent of its namespace."""

    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _parse_float(value: str, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"SVG {field} must be numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"SVG {field} must be finite: {value!r}")
    return number


def _svg_dimensions(root: ET.Element) -> tuple[float, float]:
    """Validate ``viewBox`` and return the SVG width and height."""

    view_box = root.attrib.get("viewBox")
    if not view_box:
        raise ValueError("SVG is missing viewBox")
    parts = re.split(r"[\s,]+", view_box.strip())
    if len(parts) != 4:
        raise ValueError(f"SVG viewBox must contain four numbers: {view_box!r}")
    _x, _y, view_width, view_height = (
        _parse_float(part, field="viewBox") for part in parts
    )
    if view_width <= 0 or view_height <= 0:
        raise ValueError(f"SVG viewBox dimensions must be positive: {view_box!r}")

    width_attr = root.attrib.get("width")
    height_attr = root.attrib.get("height")
    width = view_width if width_attr is None else _parse_float(width_attr, field="width")
    height = view_height if height_attr is None else _parse_float(height_attr, field="height")
    if width <= 0 or height <= 0:
        raise ValueError("SVG width and height must be positive")
    return width, height


def _remove_text_nodes(root: ET.Element) -> tuple[int, int]:
    """Remove every SVG text element and return (removed, remaining)."""

    parents: dict[ET.Element, ET.Element] = {
        child: parent for parent in root.iter() for child in list(parent)
    }
    text_nodes = [node for node in root.iter() if _local_name(node.tag) == "text"]
    for node in text_nodes:
        parent = parents.get(node)
        if parent is None:
            # The root is expected to be <svg>; a text root is invalid and
            # cannot be removed without replacing the whole document.
            raise ValueError("SVG text node has no removable parent")
        parent.remove(node)

    remaining = sum(1 for node in root.iter() if _local_name(node.tag) == "text")
    return len(text_nodes), remaining


def _clean_svg(svg_text: str | bytes) -> tuple[bytes, float, float, int, int]:
    """Parse and clean one SVG returned by PyMuPDF.

    Returns serialized UTF-8 bytes, dimensions, and text-node counts.  XML
    parser failures are surfaced as ``ValueError`` so callers cannot silently
    continue with an invalid asset.
    """

    try:
        root = ET.fromstring(svg_text)
    except (ET.ParseError, TypeError, ValueError) as exc:
        raise ValueError("failed to parse SVG returned by PyMuPDF") from exc

    if _local_name(root.tag) != "svg":
        raise ValueError("SVG root element must be <svg>")
    width, height = _svg_dimensions(root)
    removed, remaining = _remove_text_nodes(root)
    if remaining:
        raise ValueError(f"SVG still contains {remaining} text node(s) after cleaning")

    # Explicit UTF-8 bytes make the digest independent of the host locale.
    output = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return output, width, height, removed, remaining


class PageVisualExtractor:
    """Extract clean, text-free SVG visuals for a PDF page range.

    Page indexes are zero-based and the end index is exclusive, matching the
    rest of the project.  Each extracted page is written as
    ``assets/page_visuals/p####.svg`` with a neighboring
    ``p####.manifest.json`` file.  ``extract`` returns the same manifest data
    as a list of dictionaries.
    """

    def __init__(self, pdf_path: str | Path, output_dir: str | Path):
        self.pdf_path = str(pdf_path)
        self.output_dir = Path(output_dir)
        self.visual_dir = self.output_dir / "assets" / "page_visuals"
        self.doc = pymupdf.open(self.pdf_path)

    def __enter__(self) -> "PageVisualExtractor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self.doc is not None:
            self.doc.close()
            self.doc = None

    def _render_page(self, page) -> str | bytes:
        return page.get_svg_image(text_as_path=0)

    def extract(
        self,
        start_page: int = 0,
        end_page: int | None = None,
        *,
        start: int | None = None,
        end: int | None = None,
    ) -> list[dict[str, Any]]:
        """Extract pages in ``[start_page, end_page)`` and return manifests.

        ``start`` and ``end`` are accepted as concise aliases for callers that
        use ``extract(start=..., end=...)``.
        """

        if self.doc is None:
            raise RuntimeError("PageVisualExtractor is closed")
        if start is not None:
            if start_page != 0 and int(start_page) != int(start):
                raise TypeError("start_page and start disagree")
            start_page = start
        if end is not None:
            if end_page is not None and int(end_page) != int(end):
                raise TypeError("end_page and end disagree")
            end_page = end

        total = len(self.doc)
        try:
            start_index = int(start_page)
        except (TypeError, ValueError) as exc:
            raise ValueError("起始页必须是整数") from exc
        if end_page is None:
            end_index = total
        else:
            try:
                end_index = int(end_page)
            except (TypeError, ValueError) as exc:
                raise ValueError("结束页必须是整数") from exc
        if total < 1:
            raise ValueError("PDF 没有可处理页面")
        if start_index < 0 or start_index >= total:
            raise ValueError(f"起始页超出范围：PDF 共 {total} 页")
        if end_index > total:
            end_index = total
        if end_index <= start_index:
            raise ValueError("结束页必须大于起始页")

        self.visual_dir.mkdir(parents=True, exist_ok=True)
        manifests: list[dict[str, Any]] = []
        for page_index in range(start_index, end_index):
            page = self.doc[page_index]
            svg_bytes, width, height, removed, remaining = _clean_svg(
                self._render_page(page)
            )
            # If a source page has text traces but no SVG text nodes, the clean
            # result cannot be trusted and must fail loudly.
            traces = page.get_texttrace()
            if len(traces) != removed:
                raise ValueError(
                    f"page {page_index + 1} text mapping mismatch: "
                    f"{len(traces)} text traces, {removed} SVG text nodes"
                )

            stem = f"p{page_index + 1:04d}"
            svg_name = f"{stem}.svg"
            svg_path = self.visual_dir / svg_name
            svg_path.write_bytes(svg_bytes)
            digest = hashlib.sha256(svg_bytes).hexdigest()
            manifest: dict[str, Any] = {
                "page": page_index + 1,
                "svg": f"assets/page_visuals/{svg_name}",
                "width": width,
                "height": height,
                "removed_text_nodes": removed,
                "remaining_text_nodes": remaining,
                "text_trace_count": len(traces),
                "sha256": digest,
            }
            manifest_path = self.visual_dir / f"{stem}.manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            manifests.append(manifest)
        return manifests


__all__ = ["PageVisualExtractor"]
