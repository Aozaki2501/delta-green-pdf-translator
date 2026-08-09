import json
from pathlib import Path

import pytest

from exporters.typeset_pdf import (
    TypesetPDFExporter,
    write_layout_repair_manifest,
    write_layout_report,
)


def test_layout_report_is_complete_and_deterministic(tmp_path):
    output = tmp_path / "layout_issues.json"
    write_layout_report(
        [
            {
                "page": "3",
                "kind": "typeset-region-flow",
                "target": "left",
                "block_ids": ["b2", "b1"],
                "overflow_y": 8,
            },
            {
                "page": "2",
                "kind": "typeset-positioned-block",
                "target": "b3",
                "bbox": {"x": 1, "y": 2, "width": 3, "height": 4},
                "page_boundary_overflow": {"left": 5},
            },
        ],
        str(output),
    )

    data = json.loads(output.read_text(encoding="utf-8"))

    assert [item["page"] for item in data] == ["2", "3"]
    assert data[0]["bbox"]["width"] == 3
    assert data[1]["block_ids"] == ["b2", "b1"]


def test_layout_error_includes_all_targets_and_dimensions():
    with pytest.raises(RuntimeError) as error:
        TypesetPDFExporter()._raise_for_layout_issues(
            [
                {
                    "page": "2",
                    "kind": "typeset-region-flow",
                    "target": "left",
                    "block_ids": ["b1", "b2"],
                    "client_width": 100,
                    "client_height": 20,
                    "scroll_width": 100,
                    "scroll_height": 31,
                    "overflow_x": 0,
                    "overflow_y": 11,
                },
                {
                    "page": "9",
                    "kind": "typeset-positioned-block",
                    "target": "b9",
                    "overflow_x": 4,
                    "overflow_y": 0,
                },
            ]
        )

    message = str(error.value)
    assert "2 issue(s)" in message
    assert "page=2" in message
    assert "block_ids=b1,b2" in message
    assert "client=100x20 scroll=100x31" in message
    assert "page=9" in message


def test_repair_manifest_uses_measured_capacity_and_block_ids(tmp_path):
    output = tmp_path / "repair_targets.json"
    write_layout_repair_manifest(
        [
            {
                "page": "39",
                "kind": "typeset-rotated-flow",
                "target": "card-1",
                "block_ids": ["b1", "b2"],
                "bbox": {"x": 10, "y": 20, "width": 300, "height": 400},
                "client_width": 300,
                "client_height": 400,
                "scroll_width": 300,
                "scroll_height": 450,
                "overflow_x": 0,
                "overflow_y": 50,
                "page_boundary_overflow": {"left": 0, "top": 0, "right": 0, "bottom": 0},
            }
        ],
        str(output),
        profile_id="kult",
    )

    data = json.loads(output.read_text(encoding="utf-8"))

    assert data["schema_version"] == 2
    assert len(data["groups"]) == 1
    group = next(iter(data["groups"].values()))
    assert group["block_ids"] == ["b1", "b2"]
    assert group["capacity"]["overflow_y"] == 50
    assert group["target_id"] == "card-1"
    assert group["template_signature"]
    assert "300x400px" in group["constraint_prompt"]
    assert data["repair_attempt"] == 0


def test_failed_pdf_candidate_preserves_previous_output(tmp_path, monkeypatch):
    html_path = tmp_path / "book.html"
    html_path.write_text("<html></html>", encoding="utf-8")
    output = tmp_path / "book.pdf"
    output.write_bytes(b"previous-valid-pdf")

    class FakePage:
        def goto(self, *_args, **_kwargs):
            return None

        def evaluate(self, script, *_args):
            if "typesetCollectLayoutIssues" in script:
                return []
            return None

        def pdf(self, *, path, **_kwargs):
            Path(path).write_bytes(b"partial")
            raise RuntimeError("chromium export failed")

    class FakeBrowser:
        def new_page(self):
            return FakePage()

        def close(self):
            return None

    class FakePlaywright:
        chromium = type("Chromium", (), {"launch": lambda self: FakeBrowser()})()

    class FakeContext:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *_args):
            return None

    import playwright.sync_api

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: FakeContext())

    with pytest.raises(RuntimeError, match="chromium export failed"):
        TypesetPDFExporter().export(
            str(html_path), str(output), 612.0, 792.0
        )

    assert output.read_bytes() == b"previous-valid-pdf"
    assert not list(tmp_path.glob("*.candidate.pdf"))
