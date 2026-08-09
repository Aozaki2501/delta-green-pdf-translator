"""Browser-side fitting and overflow contract for fixed-page typeset HTML."""

from __future__ import annotations


def build_typeset_browser_contract() -> str:
    """Return the deterministic browser checks embedded in each fixed-page HTML."""
    return """
<script>
function typesetFitPositionedBlocks() {
  typesetFlowLineTracks();
  const boxes = document.querySelectorAll('.typeset-positioned-block[data-fit="text"]');
  for (const box of boxes) {
    box.dataset.overflow = typesetElementOverflows(box) ? 'true' : 'false';
  }
  const reflowAreas = document.querySelectorAll(
    '.typeset-reflow-area[data-fit="reflow"], .typeset-region-flow[data-fit="reflow"], .typeset-rotated-flow[data-fit="reflow"], .typeset-timeline-flow'
  );
  for (const area of reflowAreas) {
    area.dataset.overflow = typesetElementOverflows(area) ? 'true' : 'false';
  }
  typesetFitPagesToViewport();
}
function typesetFitPagesToViewport() {
  const printMode = window.matchMedia && window.matchMedia('print').matches;
  const available = Math.max(1, window.innerWidth - 24);
  for (const page of document.querySelectorAll('.typeset-page')) {
    const naturalWidth = parseFloat(page.dataset.naturalWidth || page.style.width);
    if (!naturalWidth) continue;
    page.dataset.naturalWidth = String(naturalWidth);
    const scale = printMode ? 1 : Math.min(1, available / naturalWidth);
    page.style.zoom = String(scale);
  }
}
function typesetElementOverflows(el) {
  return el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1;
}
function typesetPageBoundaryOverflow(el) {
  const page = el.closest('.typeset-page');
  if (!page) return {left: 0, top: 0, right: 0, bottom: 0};
  const pageRect = page.getBoundingClientRect();
  const rect = el.getBoundingClientRect();
  return {
    left: Math.max(0, pageRect.left - rect.left),
    top: Math.max(0, pageRect.top - rect.top),
    right: Math.max(0, rect.right - pageRect.right),
    bottom: Math.max(0, rect.bottom - pageRect.bottom),
  };
}
function typesetCollectLayoutIssues() {
  const issues = [];
  const checked = document.querySelectorAll('[data-fit="text"], [data-fit="reflow"], [data-fit="table"], .typeset-line-track-flow');
  for (const el of checked) {
    const boundary = typesetPageBoundaryOverflow(el);
    const overflow = el.dataset.overflow === 'true' || (
      !el.classList.contains('typeset-line-track-flow') && typesetElementOverflows(el)
    ) || Object.values(boundary).some((value) => value > 4);
    if (!overflow) continue;
    const page = el.closest('.typeset-page');
    issues.push({
      page: page ? page.dataset.page : '',
      kind: el.className || el.tagName,
      id: el.dataset.regionId || el.dataset.flowBlocks || el.dataset.tableBlock || el.dataset.column || '',
      target: el.dataset.blockId || el.dataset.regionId || el.dataset.flowBlocks || el.dataset.tableBlock || el.dataset.column || '',
    });
  }
  return issues;
}
function typesetFlowLineTracks() {
  const flows = document.querySelectorAll('.typeset-line-track-flow');
  for (const flow of flows) {
    const rawText = flow.dataset.flowText || '';
    const slots = Array.from(flow.querySelectorAll('.typeset-line-slot'));
    const tokens = typesetTokenizeFlowText(rawText);
    let cursor = 0;
    for (const slot of slots) {
      slot.textContent = '';
      if (cursor >= tokens.length) continue;
      let low = 0;
      let high = tokens.length - cursor;
      let best = 0;
      while (low <= high) {
        const mid = Math.floor((low + high) / 2);
        slot.textContent = tokens.slice(cursor, cursor + mid).join('');
        if (slot.scrollWidth <= slot.clientWidth + 1 && slot.scrollHeight <= slot.clientHeight + 1) {
          best = mid;
          low = mid + 1;
        } else {
          high = mid - 1;
        }
      }
      if (best <= 0) best = 1;
      slot.textContent = tokens.slice(cursor, cursor + best).join('');
      cursor += best;
    }
    flow.dataset.overflow = cursor < tokens.length ? 'true' : 'false';
  }
}
function typesetTokenizeFlowText(text) {
  const source = (text || '').replace(/\\s+/g, ' ').trim();
  if (!source) return [];
  if (/[\u4e00-\u9fff]/.test(source)) {
    const matches = source.match(/[\u4e00-\u9fff]|[^\u4e00-\u9fff\\s]+|\\s+/g) || [];
    return matches.map((item) => /^\\s+$/.test(item) ? ' ' : item);
  }
  const parts = source.split(/(\\s+)/).filter(Boolean);
  return parts.length ? parts : Array.from(source);
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', typesetFitPositionedBlocks);
} else {
  typesetFitPositionedBlocks();
}
window.addEventListener('resize', typesetFitPagesToViewport);
</script>
"""


__all__ = ["build_typeset_browser_contract"]
