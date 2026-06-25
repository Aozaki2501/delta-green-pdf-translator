import json
import os

from webui.components import _retry_export_from_audit, make_dossier_id, render_dossier_card
from webui.components import render_output_history
from webui.history import (
    collect_output_history,
    history_file_label,
    is_final_output_file,
    write_audit_record,
)


def test_make_dossier_id_is_stable_for_same_upload():
    first = make_dossier_id("book.pdf", "abcdef123456", created_at=1_700_000_000)
    second = make_dossier_id("book.pdf", "abcdef123456", created_at=1_700_000_000)

    assert first == second
    assert first.startswith("DG-")


def test_make_dossier_id_accepts_office_prefix():
    identifier = make_dossier_id(
        "book.pdf",
        "abcdef123456",
        created_at=1_700_000_000,
        prefix="DOC",
    )

    assert identifier.startswith("DOC-")


def test_render_dossier_card_uses_office_copy(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "webui.components.st.markdown",
        lambda body, unsafe_allow_html=False: calls.append((body, unsafe_allow_html)),
    )

    render_dossier_card(
        "DOC-TEST",
        "book.pdf",
        "abcdef123456",
        glossary_name="glossary.tsv",
        loaded=True,
        office_mode=True,
    )

    assert calls
    assert "DOCUMENT" in calls[0][0]
    assert "状态：待校对" in calls[0][0]
    assert "CLASSIFIED" not in calls[0][0]
    assert "绝密" not in calls[0][0]
    assert calls[0][1] is True


def test_collect_output_history_reads_audit_and_progress(tmp_path):
    output_dir = tmp_path / "output"
    folder = output_dir / "book_cn"
    folder.mkdir(parents=True)
    progress = folder / "book_cn.progress.json"
    progress.write_text(
        json.dumps({
            "metadata": {"model": "m", "provider": "p"},
            "completed_pages": [0, 1],
            "failed_pages": {"2": "timeout"},
            "translations": {"0": "a", "1": "b"},
        }),
        encoding="utf-8",
    )
    audit = folder / "book_cn_audit.json"
    write_audit_record(audit, {"dossier_id": "DG-TEST", "source_file": "book.pdf"})
    html = folder / "book_cn.html"
    html.write_text("<html></html>", encoding="utf-8")

    history = collect_output_history(output_dir)

    assert len(history) == 1
    assert history[0]["audit"]["dossier_id"] == "DG-TEST"
    assert history[0]["progress"]["completed"] == 2
    assert history[0]["progress"]["failed"] == 1
    assert history_file_label(html) == "网页"
    assert history[0]["download_files"] == [html]


def test_zip_asset_bundle_is_final_output(tmp_path):
    bundle = tmp_path / "book_typeset.html_assets.zip"
    bundle.write_bytes(b"zip")

    assert history_file_label(bundle) == "资源包"
    assert is_final_output_file(bundle) is True


def test_collect_output_history_groups_files_by_audit_outputs(tmp_path):
    output_dir = tmp_path / "output"
    folder = output_dir / "book_cn"
    folder.mkdir(parents=True)
    old_pdf = folder / "book_cn_old.pdf"
    old_pdf.write_bytes(b"%PDF-1.7\n")
    docx = folder / "book_cn.docx"
    docx.write_bytes(b"docx")
    progress = folder / "book_cn.progress.json"
    progress.write_text(
        json.dumps({
            "metadata": {},
            "completed_pages": [0],
            "failed_pages": {},
            "translations": {"0": "ok"},
        }),
        encoding="utf-8",
    )
    audit = folder / "book_cn_audit.json"
    write_audit_record(audit, {
        "dossier_id": "DG-DOCX",
        "source_file": "book.pdf",
        "outputs": [docx.name, progress.name],
    })

    history = collect_output_history(output_dir)

    assert len(history) == 1
    assert {path.name for path in history[0]["files"]} == {
        "book_cn.docx",
        "book_cn.progress.json",
        "book_cn_audit.json",
    }
    assert [path.name for path in history[0]["download_files"]] == ["book_cn.docx"]


def test_collect_output_history_uses_latest_audit_as_main_entry(tmp_path):
    output_dir = tmp_path / "output"
    folder = output_dir / "book_cn"
    folder.mkdir(parents=True)
    progress = folder / "book_cn.progress.json"
    progress.write_text(
        json.dumps({
            "metadata": {},
            "completed_pages": [0],
            "failed_pages": {},
            "translations": {"0": "ok"},
        }),
        encoding="utf-8",
    )
    old_audit = folder / "book_cn_old_audit.json"
    new_audit = folder / "book_cn_new_audit.json"
    write_audit_record(old_audit, {"dossier_id": "DG-OLD", "outputs": [progress.name]})
    write_audit_record(new_audit, {"dossier_id": "DG-NEW", "outputs": [progress.name]})
    os.utime(old_audit, (1_700_000_000, 1_700_000_000))
    os.utime(new_audit, (1_700_000_100, 1_700_000_100))

    history = collect_output_history(output_dir)

    assert len(history) == 1
    assert history[0]["audit"]["dossier_id"] == "DG-NEW"
    assert [path.name for path in history[0]["older_audits"]] == ["book_cn_old_audit.json"]


def test_history_omits_failed_metric_when_there_are_no_failures(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    folder = output_dir / "book_cn"
    folder.mkdir(parents=True)
    (folder / "book_cn.progress.json").write_text(
        json.dumps({
            "metadata": {},
            "completed_pages": [0],
            "failed_pages": {},
            "translations": {"0": "ok"},
        }),
        encoding="utf-8",
    )
    (folder / "book_cn.html").write_text("<html></html>", encoding="utf-8")
    calls = []

    class FakeColumn:
        def metric(self, label, value):
            calls.append((label, value))

    class FakeExpander:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("webui.components.st.markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr("webui.components.st.subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr("webui.components.st.caption", lambda *args, **kwargs: None)
    monkeypatch.setattr("webui.components.st.expander", lambda *args, **kwargs: FakeExpander())
    monkeypatch.setattr("webui.components.st.columns", lambda count: [FakeColumn() for _ in range(count)])
    monkeypatch.setattr("webui.components.st.download_button", lambda *args, **kwargs: None)

    render_output_history(output_dir)

    assert ("失败页", "0") not in calls


def test_retry_export_from_audit_reuses_progress_and_updates_audit(tmp_path, monkeypatch):
    folder = tmp_path / "book_cn"
    folder.mkdir()
    progress = folder / "book_cn.progress.json"
    progress.write_text(
        json.dumps({
            "translations": {"0": "正文。"},
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    audit_path = folder / "book_cn_audit.json"
    write_audit_record(audit_path, {
        "dossier_id": "DG-RETRY",
        "source_file": "book.pdf",
        "status": "export_failed",
        "formats": ["html"],
        "progress_path": str(progress),
        "output_base": str(folder / "book_cn"),
        "output_options": {"columns": 1},
        "retryable_export": True,
        "export_errors": ["html failed"],
        "outputs": [],
    })
    calls = []

    def fake_rerender(**kwargs):
        calls.append(kwargs)
        html_path = folder / "book_cn.html"
        html_path.write_text("<html></html>", encoding="utf-8")
        return [str(html_path)]

    monkeypatch.setattr("rerender_output.rerender_selected_outputs", fake_rerender)

    written = _retry_export_from_audit({
        "audit": json.loads(audit_path.read_text(encoding="utf-8")),
        "audit_path": audit_path,
        "title": "book_cn",
        "folder": folder,
    })

    updated = json.loads(audit_path.read_text(encoding="utf-8"))
    assert written == [str(folder / "book_cn.html")]
    assert calls[0]["progress_path"] == str(progress)
    assert calls[0]["output_formats"] == ["html"]
    assert calls[0]["columns"] == 1
    assert updated["status"] == "completed"
    assert updated["retryable_export"] is False
    assert updated["export_errors"] == []
    assert updated["outputs"] == ["book_cn.html"]
