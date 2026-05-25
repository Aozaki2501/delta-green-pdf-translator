import json

from webui.components import make_dossier_id
from webui.components import render_output_history
from webui.history import collect_output_history, history_file_label, write_audit_record


def test_make_dossier_id_is_stable_for_same_upload():
    first = make_dossier_id("book.pdf", "abcdef123456", created_at=1_700_000_000)
    second = make_dossier_id("book.pdf", "abcdef123456", created_at=1_700_000_000)

    assert first == second
    assert first.startswith("DG-")


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


def test_collect_output_history_reads_replica_outputs(tmp_path):
    output_dir = tmp_path / "output"
    folder = output_dir / "book_cn"
    folder.mkdir(parents=True)
    progress = folder / "book_cn_replica.progress.json"
    progress.write_text(
        json.dumps({
            "schema": 1,
            "translations": {"p0001_t0000": "译文"},
            "failed_blocks": {"p0001_t0001": "timeout"},
        }),
        encoding="utf-8",
    )
    replica_pdf = folder / "book_cn_replica.pdf"
    replica_pdf.write_bytes(b"%PDF-1.7\n")
    overflow = folder / "book_cn_replica.overflow.md"
    overflow.write_text("overflow", encoding="utf-8")

    history = collect_output_history(output_dir)

    assert len(history) == 1
    assert history[0]["progress"]["completed"] == 1
    assert history[0]["progress"]["failed"] == 1
    assert history_file_label(replica_pdf) == "坐标PDF"
    assert history_file_label(overflow) == "坐标溢出报告"


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
