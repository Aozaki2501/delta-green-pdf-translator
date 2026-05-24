#!/usr/bin/env python3
"""
Delta Green PDF Translator — Web UI (Streamlit)
"""
import streamlit as st
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from translate_pdf import (
    PDFExtractor, Translator, ProgressTracker, TokenStats,
    load_glossary, translate_batch_concurrent,
    write_markdown_output, write_html_output, write_word_output, HAS_DOCX,
    build_progress_metadata, parse_page_selection, write_glossary_report,
    normalize_page_range, is_failed_translation, build_extraction_diagnostics_report,
    find_relevant_glossary_terms,
)
from core.glossary_editor import (
    glossary_rows_to_tsv,
    parse_glossary_editor_text,
    read_glossary_editor_text,
)


APP_DIR = Path(__file__).resolve().parent
DEFAULT_GLOSSARY_PATH = APP_DIR / "glossary.tsv"
OUTPUT_FORMAT_LABELS = {
    "markdown": "纯文本稿",
    "html": "网页排版",
    "word": "文档排版",
}
HISTORY_SCHEMA = 1


def make_output_path(output_base, extension):
    """Return a non-overwriting output path for Web downloads."""
    path = output_base + extension
    if not os.path.exists(path):
        return path
    return f"{output_base}_{uuid.uuid4().hex[:8]}{extension}"


def format_duration(seconds):
    if seconds is None:
        return "估算中"
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def format_file_size(size_bytes):
    size = max(0, int(size_bytes or 0))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} GB"


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def safe_filename_stem(filename: str, default: str = "document") -> str:
    stem = Path(filename or default).stem
    stem = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", stem).strip("._-")
    return stem or default


def history_file_for_progress(progress_path: Path) -> Path:
    if progress_path.name.endswith(".progress.json"):
        return progress_path.with_name(
            progress_path.name[:-len(".progress.json")] + ".history.json"
        )
    return progress_path.with_suffix(".history.json")


def list_task_output_files(task_dir: Path) -> list[dict]:
    if not task_dir.exists():
        return []
    files = []
    allowed_suffixes = {".docx", ".html", ".md"}
    for path in sorted(task_dir.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        if path.name.endswith((".progress.json", ".history.json")):
            continue
        if path.suffix.lower() not in allowed_suffixes:
            continue
        files.append({
            "path": str(path),
            "name": path.name,
            "size": path.stat().st_size,
        })
    return files


def load_progress_history_record(progress_path: Path) -> dict:
    task_dir = progress_path.parent
    record = {
        "title": task_dir.name,
        "progress_path": str(progress_path),
        "updated_at": progress_path.stat().st_mtime,
        "status": "可继续",
        "error": "",
        "model": "",
        "provider": "",
        "page_range": "",
        "completed_pages": 0,
        "failed_pages": 0,
        "cost_yuan": None,
        "total_tokens": None,
        "workers": None,
        "files": list_task_output_files(task_dir),
    }
    try:
        with open(progress_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("progress root must be an object")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        completed_pages = data.get("completed_pages", [])
        failed_pages = data.get("failed_pages", {})
        record["model"] = str(metadata.get("model", ""))
        record["provider"] = str(metadata.get("provider", ""))
        start_page = metadata.get("start_page")
        end_page = metadata.get("end_page")
        if isinstance(start_page, int) and isinstance(end_page, int):
            record["page_range"] = f"{start_page + 1}-{end_page}"
        record["completed_pages"] = len(completed_pages) if isinstance(completed_pages, list) else 0
        record["failed_pages"] = len(failed_pages) if isinstance(failed_pages, dict) else 0
        if record["failed_pages"]:
            record["status"] = "有失败页"
        elif record["completed_pages"]:
            record["status"] = "已有译文"
    except json.JSONDecodeError as exc:
        record["status"] = "进度文件损坏"
        record["error"] = f"{exc.msg}，第 {exc.lineno} 行"
    except (OSError, ValueError, TypeError) as exc:
        record["status"] = "进度文件异常"
        record["error"] = str(exc)

    history_path = history_file_for_progress(progress_path)
    if history_path.exists():
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            if not isinstance(manifest, dict):
                raise ValueError("history root must be an object")
            record["title"] = str(manifest.get("title") or record["title"])
            record["cost_yuan"] = manifest.get("cost_yuan")
            record["total_tokens"] = manifest.get("total_tokens")
            record["workers"] = manifest.get("workers")
            record["updated_at"] = max(record["updated_at"], history_path.stat().st_mtime)
        except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
            record["status"] = "历史清单异常"
            record["error"] = str(exc)
    return record


def collect_output_history(output_dir: Path, limit: int = 8) -> list[dict]:
    if not output_dir.exists():
        return []
    records = [
        load_progress_history_record(path)
        for path in output_dir.rglob("*.progress.json")
        if path.is_file()
    ]
    records.sort(key=lambda item: item["updated_at"], reverse=True)
    return records[:limit]


def remember_generated_file(files: list[dict], path: str, label: str):
    file_path = Path(path)
    files.append({
        "label": label,
        "path": str(file_path),
        "name": file_path.name,
        "size": file_path.stat().st_size if file_path.exists() else 0,
    })


def write_history_manifest(output_base: str, title: str, progress_file: str, formats: list[str],
                           generated_files: list[dict], stats: TokenStats, workers: int,
                           model: str, provider: str, completed_pages: int,
                           failed_pages: list[int]):
    history_path = history_file_for_progress(Path(progress_file))
    manifest = {
        "schema": HISTORY_SCHEMA,
        "title": title,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "output_base": output_base,
        "progress_file": progress_file,
        "formats": list(formats),
        "files": generated_files,
        "model": model,
        "provider": provider,
        "workers": int(workers),
        "completed_pages": int(completed_pages),
        "failed_pages": list(failed_pages),
        "cost_yuan": round(float(stats.cost_yuan), 6),
        "total_tokens": int(stats.total_tokens),
    }
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def render_output_history(output_dir: Path):
    with st.expander("输出历史", expanded=False):
        records = collect_output_history(output_dir)
        if not records:
            st.caption("还没有历史输出。完成一次翻译后，这里会显示最近任务。")
            return
        for index, record in enumerate(records):
            updated = time.strftime(
                "%Y-%m-%d %H:%M",
                time.localtime(record["updated_at"]),
            )
            st.markdown(f"**{record['title']}**")
            facts = [
                f"状态：{record['status']}",
                f"更新时间：{updated}",
                f"页数：{record['completed_pages']}",
            ]
            if record["failed_pages"]:
                facts.append(f"失败页：{record['failed_pages']}")
            if record["page_range"]:
                facts.append(f"范围：{record['page_range']}")
            if record["model"]:
                facts.append(f"模型：{record['model']}")
            if record["workers"]:
                facts.append(f"并发：{record['workers']}")
            if record["cost_yuan"] is not None:
                facts.append(f"费用：¥{float(record['cost_yuan']):.3f}")
            else:
                facts.append("费用：未记录")
            st.caption(" | ".join(facts))
            if record["error"]:
                st.error(record["error"])
            files = record["files"]
            if files:
                cols = st.columns(min(4, len(files)))
                for file_index, file_info in enumerate(files):
                    path = Path(file_info["path"])
                    if not path.exists():
                        continue
                    label = f"{path.name} ({format_file_size(path.stat().st_size)})"
                    with open(path, "rb") as f:
                        cols[file_index % len(cols)].download_button(
                            label,
                            f,
                            file_name=path.name,
                            key=f"history-download-{index}-{file_index}",
                        )
            st.code(record["progress_path"], language="text")


def render_glossary_manager(glossary_path: Path):
    with st.expander("术语表管理", expanded=False):
        st.caption(f"当前管理文件：{glossary_path.name}")
        if st.button("重新载入术语表", key="reload-glossary"):
            st.session_state["glossary_editor_text"] = read_glossary_editor_text(glossary_path)
        if "glossary_editor_text" not in st.session_state:
            st.session_state["glossary_editor_text"] = read_glossary_editor_text(glossary_path)

        rows, errors, warnings = parse_glossary_editor_text(st.session_state["glossary_editor_text"])
        search_text = st.text_input("搜索术语", value="", key="glossary-search")
        if search_text.strip():
            keyword = search_text.strip().lower()
            matches = [
                row for row in rows
                if keyword in row["english"].lower() or keyword in row["chinese"].lower()
            ][:30]
            if matches:
                st.table([
                    {"行": row["line"], "中文译名": row["chinese"], "英文原名": row["english"]}
                    for row in matches
                ])
            else:
                st.caption("没有匹配项。")

        col_a, col_b = st.columns(2)
        new_chinese = col_a.text_input("新增中文译名", key="glossary-new-chinese")
        new_english = col_b.text_input("新增英文原名", key="glossary-new-english")
        if st.button("加入编辑区", key="append-glossary-term"):
            if not new_chinese.strip() or not new_english.strip():
                st.error("新增术语必须同时填写中文译名和英文原名。")
            else:
                current = st.session_state["glossary_editor_text"].rstrip()
                appended = f"{new_chinese.strip()}\t{new_english.strip()}"
                st.session_state["glossary_editor_text"] = (current + "\n" + appended + "\n").lstrip("\n")
                st.rerun()

        st.text_area(
            "TSV 编辑区",
            key="glossary_editor_text",
            height=320,
            help="每行一条：中文译名、Tab、英文原名。",
        )
        rows, errors, warnings = parse_glossary_editor_text(st.session_state["glossary_editor_text"])
        st.caption(f"有效术语：{len(rows)} 条")
        for warning in warnings[:8]:
            st.warning(warning)
        for error in errors[:8]:
            st.error(error)
        if len(errors) > 8:
            st.error(f"还有 {len(errors) - 8} 个错误未显示。")

        if st.button("保存术语表", key="save-glossary", type="primary"):
            if errors:
                st.error("术语表仍有错误，未保存。")
            else:
                normalized = glossary_rows_to_tsv(rows)
                with open(glossary_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(normalized)
                st.success(f"已保存 {len(rows)} 条术语。")


def page_numbers_to_selection(page_numbers) -> str:
    return ", ".join(str(page) for page in sorted({int(page) for page in page_numbers}))


def render_recovery_action_panel(failed_pages: list[int], risky_pages: list[int], empty_pages: list[int]):
    all_targets = sorted(set(failed_pages) | set(risky_pages) | set(empty_pages))
    if not all_targets:
        return
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("失败页和风险页")
    cols = st.columns(4)
    cols[0].metric("失败页", f"{len(failed_pages)}")
    cols[1].metric("风险页", f"{len(risky_pages)}")
    cols[2].metric("空页", f"{len(empty_pages)}")
    cols[3].metric("可处理页", f"{len(all_targets)}")
    if failed_pages:
        st.warning("失败页：" + page_numbers_to_selection(failed_pages))
    if risky_pages:
        st.warning("风险页：" + page_numbers_to_selection(risky_pages))
    if empty_pages:
        st.warning("空页：" + page_numbers_to_selection(empty_pages))

    target_text = page_numbers_to_selection(all_targets)
    st.text_area("可直接重翻的页码", value=target_text, height=90, disabled=True)
    if st.button("填入重翻页码", key="use-recovery-pages"):
        st.session_state["pending_retranslate_pages_text"] = target_text
        st.session_state.pop("preflight_report", None)
        st.info("已填入重翻页码。重新预检后即可执行重翻。")
        st.rerun()
    if failed_pages and st.button("下次只重试失败页", key="retry-failed-next"):
        st.session_state["pending_retry_failed_pages"] = True
        st.session_state.pop("preflight_report", None)
        st.info("已勾选只重试失败页。重新预检后即可执行。")
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def uploaded_file_digest(uploaded_file) -> str:
    return hashlib.sha256(uploaded_file.getvalue()).hexdigest()


def local_file_digest(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_current_task_signature(pdf_file, glossary_file, start_page, end_page_text,
                                 formats, model, provider, base_url, workers,
                                 retry_failed_pages, retranslate_pages_text):
    if not pdf_file:
        return ""
    glossary_sha = (
        uploaded_file_digest(glossary_file)
        if glossary_file else local_file_digest(DEFAULT_GLOSSARY_PATH)
    )
    payload = {
        "pdf_sha256": uploaded_file_digest(pdf_file),
        "glossary_sha256": glossary_sha,
        "start_page": int(start_page),
        "end_page_text": str(end_page_text or ""),
        "formats": sorted(formats),
        "model": str(model),
        "provider": str(provider),
        "base_url": str(base_url),
        "workers": int(workers),
        "retry_failed_pages": bool(retry_failed_pages),
        "retranslate_pages_text": str(retranslate_pages_text or ""),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def save_uploaded_pdf_for_preview(uploaded_file) -> Path:
    upload_dir = APP_DIR / "uploads"
    ensure_dir(upload_dir)
    digest = uploaded_file_digest(uploaded_file)[:12]
    target = upload_dir / f"_preview_{safe_filename_stem(uploaded_file.name)}_{digest}.pdf"
    if not target.exists():
        with open(target, "wb") as f:
            f.write(uploaded_file.getvalue())
    return target


def save_uploaded_glossary_for_preflight(uploaded_file) -> Path:
    upload_dir = APP_DIR / "uploads"
    ensure_dir(upload_dir)
    digest = uploaded_file_digest(uploaded_file)[:12]
    suffix = Path(uploaded_file.name).suffix.lower() or ".tsv"
    target = upload_dir / f"_preflight_{safe_filename_stem(uploaded_file.name, 'glossary')}_{digest}{suffix}"
    if not target.exists():
        with open(target, "wb") as f:
            f.write(uploaded_file.getvalue())
    return target


def estimate_preflight_cost_yuan(source_chars: int, page_count: int) -> float:
    input_tokens = max(1, source_chars // 4 + page_count * 450)
    output_tokens = max(1, int(input_tokens * 0.9))
    return (
        input_tokens * TokenStats.PRICE_INPUT_PER_M / 1_000_000
        + output_tokens * TokenStats.PRICE_OUTPUT_PER_M / 1_000_000
    )


def build_preflight_report(pdf_file, glossary_file, start_page_input, end_page_text,
                           model: str, workers: int, signature: str) -> dict:
    pdf_path = save_uploaded_pdf_for_preview(pdf_file)
    glossary_path = (
        save_uploaded_glossary_for_preflight(glossary_file)
        if glossary_file else DEFAULT_GLOSSARY_PATH if DEFAULT_GLOSSARY_PATH.exists() else None
    )
    glossary = load_glossary(str(glossary_path)) if glossary_path else {}
    extractor = PDFExtractor(str(pdf_path))
    try:
        total_pages = extractor.total_pages
        start_page = int(start_page_input) - 1
        end_page = int(end_page_text) if str(end_page_text or "").strip() else None
        start_page, end_page = normalize_page_range(start_page, end_page, total_pages)

        page_diagnostics = []
        total_chars = 0
        total_images = 0
        total_glossary_hits = 0
        risky_pages = []
        empty_pages = []
        for page_num in range(start_page, end_page):
            extractor.detect_page_layout(page_num)
            text = extractor.extract_page(page_num)
            diagnostics = extractor.get_page_diagnostics(page_num, text)
            page_diagnostics.append(diagnostics)
            total_chars += diagnostics["text_length"]
            total_images += diagnostics["image_count"]
            hits = find_relevant_glossary_terms(text, glossary)
            total_glossary_hits += len(hits)
            if diagnostics["risks"]:
                risky_pages.append(page_num + 1)
            if not text.strip():
                empty_pages.append(page_num + 1)

        page_count = end_page - start_page
        speed = max(1, min(int(workers or 1), page_count or 1))
        estimated_seconds = max(1, int((page_count / speed) * 50))
        return {
            "signature": signature,
            "pdf_name": pdf_file.name,
            "model": model,
            "workers": int(workers),
            "total_pages": total_pages,
            "start_page": start_page + 1,
            "end_page": end_page,
            "page_count": page_count,
            "total_chars": total_chars,
            "image_count": total_images,
            "glossary_terms": len(glossary),
            "glossary_hits": total_glossary_hits,
            "risky_pages": risky_pages,
            "empty_pages": empty_pages,
            "estimated_cost_yuan": estimate_preflight_cost_yuan(total_chars, page_count),
            "estimated_seconds": estimated_seconds,
            "diagnostics": page_diagnostics,
        }
    finally:
        extractor.close()


def render_preflight_report(report: dict):
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("任务预检")
    cols = st.columns(5)
    cols[0].metric("页数", f"{report['page_count']}")
    cols[1].metric("风险页", f"{len(report['risky_pages'])}")
    cols[2].metric("空页", f"{len(report['empty_pages'])}")
    cols[3].metric("图片", f"{report['image_count']}")
    cols[4].metric("术语命中", f"{report['glossary_hits']}")
    st.caption(
        f"范围：第 {report['start_page']} 到 {report['end_page']} 页 | "
        f"模型：{report['model']} | 并发：{report['workers']} | "
        f"预计费用：¥{report['estimated_cost_yuan']:.3f} | "
        f"预计耗时：{format_duration(report['estimated_seconds'])}"
    )
    if report["risky_pages"]:
        st.warning("风险页：" + ", ".join(map(str, report["risky_pages"][:40])))
    if report["empty_pages"]:
        st.warning("空页：" + ", ".join(map(str, report["empty_pages"][:40])))
    st.markdown("</div>", unsafe_allow_html=True)


# === UI THEME ===
st.set_page_config(
    page_title="三角洲翻译终端",
    page_icon="🖧",
    layout="wide",
)

st.markdown("""
<style>
    :root {
        --bg: #030604;
        --panel: rgba(5, 13, 8, 0.86);
        --panel-strong: rgba(8, 22, 13, 0.94);
        --line: rgba(69, 255, 129, 0.24);
        --line-hot: rgba(81, 255, 137, 0.72);
        --green: #52ff91;
        --green-soft: #9dffc1;
        --amber: #ffd166;
        --red: #ff4d4d;
        --text: #c8d8c9;
        --muted: #7f9b85;
        --shadow: rgba(82, 255, 145, 0.18);
    }

    .stApp, .stAppHeader {
        background:
            linear-gradient(rgba(82, 255, 145, 0.035) 1px, transparent 1px),
            linear-gradient(90deg, rgba(82, 255, 145, 0.025) 1px, transparent 1px),
            radial-gradient(circle at 12% 8%, rgba(82, 255, 145, 0.12), transparent 30%),
            radial-gradient(circle at 88% 28%, rgba(255, 77, 77, 0.08), transparent 26%),
            var(--bg) !important;
        background-size: 28px 28px, 28px 28px, auto, auto, auto !important;
        color: var(--text) !important;
        font-family: "SimHei", "Microsoft YaHei", "Noto Sans SC", sans-serif !important;
    }

    #MainMenu,
    footer,
    header[data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    .stDeployButton {
        display: none !important;
        visibility: hidden !important;
    }

    .stApp::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        z-index: 9999;
        background:
            linear-gradient(rgba(255, 255, 255, 0.018) 50%, rgba(0, 0, 0, 0.12) 50%),
            linear-gradient(90deg, rgba(255, 0, 0, 0.018), rgba(0, 255, 64, 0.012), rgba(0, 96, 255, 0.018));
        background-size: 100% 4px, 6px 100%;
        mix-blend-mode: screen;
        opacity: 0.32;
    }

    .stApp::after {
        content: "";
        position: fixed;
        left: 0;
        right: 0;
        top: -20%;
        height: 18%;
        pointer-events: none;
        z-index: 9998;
        background: linear-gradient(180deg, transparent, rgba(82, 255, 145, 0.12), transparent);
        animation: dg-scan 6.5s linear infinite;
    }

    @keyframes dg-scan {
        0% { transform: translateY(-10vh); }
        100% { transform: translateY(130vh); }
    }

    @keyframes panel-in {
        from { opacity: 0; transform: translateY(14px); }
        to { opacity: 1; transform: translateY(0); }
    }

    @keyframes pulse-line {
        0%, 100% { box-shadow: 0 0 0 rgba(82, 255, 145, 0); }
        50% { box-shadow: 0 0 28px var(--shadow); }
    }

    @media (prefers-reduced-motion: reduce) {
        .stApp::after, .boot-screen, .classified-hero, .section-card, .intel-tile { animation: none !important; }
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(4, 12, 7, 0.98), rgba(2, 7, 4, 0.98)) !important;
        border-right: 1px solid var(--line) !important;
        box-shadow: 12px 0 36px rgba(0, 0, 0, 0.42);
    }

    h1, h2, h3, .hero-title {
        color: var(--green) !important;
        font-family: "SimHei", "Microsoft YaHei", "Noto Sans SC", sans-serif !important;
        letter-spacing: 0;
        font-weight: 900;
    }

    p, label, .stMarkdown {
        color: var(--text) !important;
        font-size: 0.95rem;
    }

    .block-container {
        max-width: 1220px;
        padding-top: 1.5rem;
        padding-bottom: 4rem;
    }

    .classified-hero {
        position: relative;
        overflow: hidden;
        border: 1px solid var(--line-hot);
        background:
            linear-gradient(135deg, rgba(82, 255, 145, 0.13), transparent 42%),
            linear-gradient(180deg, rgba(7, 28, 14, 0.92), rgba(3, 8, 5, 0.86));
        padding: 26px 28px;
        margin-bottom: 18px;
        animation: panel-in 420ms ease-out, pulse-line 5s ease-in-out infinite;
    }

    .classified-hero::before {
        content: "绝密";
        position: absolute;
        right: -44px;
        top: 28px;
        transform: rotate(34deg);
        color: rgba(255, 77, 77, 0.24);
        border: 2px solid rgba(255, 77, 77, 0.24);
        padding: 6px 44px;
        font: 26px "SimHei", "Microsoft YaHei", sans-serif;
        letter-spacing: 0;
    }

    .hero-title {
        font-size: 3rem;
        line-height: 0.9;
        margin-bottom: 10px;
        text-shadow: 0 0 18px rgba(82, 255, 145, 0.34);
    }

    .hero-subtitle {
        color: var(--green-soft);
        font-size: 0.96rem;
        line-height: 1.65;
    }

    .terminal-line {
        color: var(--muted);
        margin-top: 14px;
        font-size: 0.86rem;
    }

    .terminal-cursor {
        display: inline-block;
        width: 9px;
        height: 1.05em;
        margin-left: 4px;
        background: var(--green);
        vertical-align: -0.15em;
        animation: blink 1s steps(1) infinite;
    }

    @keyframes blink {
        50% { opacity: 0; }
    }

    .intel-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
        margin-bottom: 18px;
    }

    .intel-tile, .section-card {
        border: 1px solid var(--line);
        background: var(--panel);
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.24);
        animation: panel-in 520ms ease-out both;
    }

    .intel-tile {
        padding: 12px 14px;
    }

    .intel-label {
        color: var(--muted);
        font-size: 0.72rem;
        text-transform: uppercase;
    }

    .intel-value {
        color: var(--green-soft);
        font: 1.5rem "SimHei", "Microsoft YaHei", sans-serif;
        margin-top: 2px;
    }

    .section-card {
        position: relative;
        padding: 20px;
        margin: 16px 0;
    }

    .section-card::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        width: 4px;
        height: 100%;
        background: linear-gradient(var(--green), transparent);
    }

    div[data-testid="stFileUploader"] {
        background: rgba(5, 18, 9, 0.7) !important;
        border: 1px dashed var(--line-hot) !important;
        border-radius: 0 !important;
        padding: 16px;
        transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
    }

    div[data-testid="stFileUploader"]:hover {
        border-color: var(--green) !important;
        box-shadow: 0 0 28px rgba(82, 255, 145, 0.16);
        transform: translateY(-1px);
    }

    .stTextInput input,
    .stNumberInput input,
    .stSelectbox div[data-baseweb="select"],
    .stMultiSelect div[data-baseweb="select"] {
        background-color: rgba(3, 9, 5, 0.95) !important;
        border: 1px solid var(--line) !important;
        border-radius: 0 !important;
        color: var(--green-soft) !important;
        font-family: "Courier Prime", monospace !important;
    }

    div[data-testid="stFileUploader"] button {
        font-size: 0 !important;
    }

    div[data-testid="stFileUploader"] button::after {
        content: "导入";
        font-size: 0.95rem;
    }

    div[data-testid="stFileUploader"] small {
        font-size: 0 !important;
    }

    .stTextInput input:focus,
    .stNumberInput input:focus {
        border-color: var(--green) !important;
        box-shadow: 0 0 0 1px rgba(82, 255, 145, 0.35) !important;
    }

    .stButton>button {
        position: relative;
        overflow: hidden;
        background: linear-gradient(90deg, rgba(82, 255, 145, 0.08), rgba(82, 255, 145, 0.02)) !important;
        color: var(--green) !important;
        border: 1px solid var(--line-hot) !important;
        border-radius: 0 !important;
        height: 48px;
        font-weight: bold;
        letter-spacing: 0;
        transition: all 0.18s ease;
        text-transform: uppercase;
    }

    .stButton>button:hover {
        background: var(--green) !important;
        color: #031006 !important;
        box-shadow: 0 0 26px rgba(82, 255, 145, 0.34);
    }

    .stProgress > div > div > div {
        background-color: var(--green) !important;
        box-shadow: 0 0 16px rgba(82, 255, 145, 0.52);
    }

    div[data-testid="stMetric"] {
        background: var(--panel-strong) !important;
        border: 1px solid var(--line) !important;
        border-radius: 0 !important;
        padding: 15px;
    }
    
    div[data-testid="stMetricValue"] {
        color: var(--green) !important;
    }

    [data-testid="stExpander"] {
        background: rgba(4, 12, 7, 0.74) !important;
        border: 1px solid var(--line) !important;
        border-radius: 0 !important;
    }

    .stAlert {
        border-radius: 0 !important;
    }

    textarea {
        background: rgba(2, 8, 4, 0.95) !important;
        color: var(--green-soft) !important;
        border: 1px solid var(--line) !important;
        font-family: "Courier Prime", monospace !important;
    }

    .boot-screen {
        position: fixed;
        inset: 0;
        z-index: 10000;
        pointer-events: none;
        display: grid;
        place-items: center;
        background:
            linear-gradient(rgba(82, 255, 145, 0.05) 1px, transparent 1px),
            linear-gradient(90deg, rgba(82, 255, 145, 0.04) 1px, transparent 1px),
            #020503;
        background-size: 30px 30px;
        animation: boot-hide 3.7s ease forwards;
    }

    .boot-panel {
        width: min(680px, calc(100vw - 44px));
        border: 1px solid var(--line-hot);
        background: rgba(3, 12, 6, 0.92);
        box-shadow: 0 0 52px rgba(82, 255, 145, 0.18);
        padding: 28px;
        font-family: "SimHei", "Microsoft YaHei", sans-serif;
    }

    .boot-title {
        color: var(--green);
        font-size: 2.2rem;
        font-weight: 900;
        letter-spacing: 0;
        margin-bottom: 14px;
    }

    .boot-lines {
        color: var(--green-soft);
        font-family: "Courier New", monospace;
        line-height: 1.8;
        font-size: 0.95rem;
    }

    .boot-bar {
        height: 8px;
        margin-top: 22px;
        border: 1px solid var(--line);
        background: rgba(82, 255, 145, 0.06);
        overflow: hidden;
    }

    .boot-bar::before {
        content: "";
        display: block;
        height: 100%;
        width: 0;
        background: var(--green);
        box-shadow: 0 0 18px rgba(82, 255, 145, 0.65);
        animation: boot-load 2.45s steps(18) forwards;
    }

    .boot-stamp {
        margin-top: 16px;
        color: rgba(255, 77, 77, 0.82);
        border: 1px solid rgba(255, 77, 77, 0.56);
        display: inline-block;
        padding: 4px 10px;
        transform: rotate(-2deg);
        font-weight: 900;
    }

    @keyframes boot-load {
        to { width: 100%; }
    }

    @keyframes boot-hide {
        0%, 72% { opacity: 1; visibility: visible; }
        100% { opacity: 0; visibility: hidden; }
    }

    @media (max-width: 760px) {
        .intel-grid {
            grid-template-columns: 1fr;
        }
        .hero-title {
            font-size: 2.2rem;
        }
    }
</style>
""", unsafe_allow_html=True)

# === HEADER ===
st.markdown("""
<div class="boot-screen">
    <div class="boot-panel">
        <div class="boot-title">绝密系统接入中</div>
        <div class="boot-lines">
            > 正在校验操作员密钥<br>
            > 正在载入译文编译协议<br>
            > 正在建立黑色档案通道
        </div>
        <div class="boot-bar"></div>
        <div class="boot-stamp">TOP SECRET</div>
    </div>
</div>
<div class="classified-hero">
    <div class="hero-title">三角洲翻译终端</div>
    <div class="hero-subtitle">
        > 访问等级：黑色绝密<br>
        > 执行协议：文本提取 / 术语锁定 / 译文编译<br>
        > 终端状态：等待导入档案
    </div>
    <div class="terminal-line">系统就绪<span class="terminal-cursor"></span></div>
</div>
<div class="intel-grid">
    <div class="intel-tile">
        <div class="intel-label">任务</div>
        <div class="intel-value">翻译</div>
    </div>
    <div class="intel-tile">
        <div class="intel-label">输出</div>
        <div class="intel-value">网页 / 文档</div>
    </div>
    <div class="intel-tile">
        <div class="intel-label">模式</div>
        <div class="intel-value">私密校对</div>
    </div>
</div>
""", unsafe_allow_html=True)

if "pending_retranslate_pages_text" in st.session_state:
    st.session_state["retranslate_pages_text"] = st.session_state.pop("pending_retranslate_pages_text")
if st.session_state.pop("pending_retry_failed_pages", False):
    st.session_state["retry_failed_pages"] = True

with st.sidebar:
    st.header("任务控制台")

    provider = "deepseek"
    base_url = "https://api.deepseek.com"
    model = "deepseek-v4-pro"
    workers = 32
    retranslate_pages_str = ""
    retry_failed_pages = False
    reuse_mismatched_progress = False
    show_extraction_preview = False
    preview_page = 1
    word_body_font_size = 12.0
    word_line_spacing = 1.5
    word_columns = 2
    word_min_chars = 1000
    word_max_chars = 1500
    word_hard_page_breaks = False
    word_header_left = "绿色三角洲"
    word_header_right = ""

    st.caption("必要项")
    api_key = st.text_input("接口密钥", type="password", placeholder="sk-...")

    formats = st.multiselect(
        "输出格式",
        ["markdown", "html", "word"],
        default=["html", "word"],
        format_func=lambda value: OUTPUT_FORMAT_LABELS[value],
    )

    display_start_page = st.number_input("起始页（从 1 开始）", value=1, min_value=1)
    end_page_str = st.text_input("结束页（含，从 1 开始）", value="", placeholder="留空表示全部")

    with st.expander("高级任务控制", expanded=False):
        model = st.text_input("模型名称", value=model)
        workers = st.slider("并发线程", 1, 64, 32)
        retranslate_pages_str = st.text_input(
            "重翻页码",
            placeholder="如：8, 12-15",
            key="retranslate_pages_text",
        )
        retry_failed_pages = st.checkbox(
            "只重试失败页",
            key="retry_failed_pages",
        )
        show_extraction_preview = st.checkbox("显示提取预览", value=False)
        if show_extraction_preview:
            preview_page = st.number_input("预览页（从 1 开始）", value=1, min_value=1)

    if "word" in formats:
        with st.expander("文档档案输出", expanded=False):
            word_body_font_size = st.slider("正文字号", 9.0, 14.0, 12.0, 0.5)
            word_line_spacing = st.slider("正文行距", 1.0, 2.0, 1.5, 0.05)
            word_columns = st.selectbox("正文分栏", [1, 2], index=1, format_func=lambda n: f"{n} 栏")
            word_min_chars = st.number_input("阅读页最少字数", value=1000, min_value=300, max_value=3000, step=100)
            word_max_chars = st.number_input("阅读页最多字数", value=1500, min_value=500, max_value=5000, step=100)
            word_hard_page_breaks = st.checkbox(
                "按阅读页强制分页",
                value=False,
                help="关闭时文档会自然续排，减少半页空白；开启时每个阅读页后插入分页符。",
            )
            word_header_left = st.text_input("页眉左侧", value="绿色三角洲")
            word_header_right = st.text_input("页眉右侧", value="", placeholder="留空则使用文件名")

# === MAIN ===
st.markdown('<div class="section-card">', unsafe_allow_html=True)

st.subheader("导入机密档案")
st.caption("上传原始 PDF。默认加载本地 glossary.tsv；只有需要替换术语时再上传自定义文件。")

col1, col2 = st.columns([1.2, 1])
with col1:
    pdf_file = st.file_uploader("PDF 档案", type=["pdf"], label_visibility="collapsed")
with col2:
    glossary_file = st.file_uploader("替换术语表，可选", type=["tsv", "txt", "csv"], label_visibility="collapsed")
    if glossary_file:
        st.caption(f"将使用上传术语表：{glossary_file.name}")
    elif DEFAULT_GLOSSARY_PATH.exists():
        st.caption("将使用默认术语表：glossary.tsv")
    else:
        st.caption("未找到默认术语表；可上传自定义术语表。")

st.markdown("</div>", unsafe_allow_html=True)

render_output_history(APP_DIR / "output")
render_glossary_manager(DEFAULT_GLOSSARY_PATH)

current_task_signature = build_current_task_signature(
    pdf_file,
    glossary_file,
    display_start_page,
    end_page_str,
    formats,
    model,
    provider,
    base_url,
    workers,
    retry_failed_pages,
    retranslate_pages_str,
)
preflight_report = st.session_state.get("preflight_report")
preflight_ready = (
    bool(pdf_file)
    and isinstance(preflight_report, dict)
    and preflight_report.get("signature") == current_task_signature
)

if pdf_file:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("翻译前预检")
    st.caption("先扫描页数、风险、图片和术语命中；确认后再执行翻译。")
    if st.button("生成任务预检", use_container_width=True):
        try:
            report = build_preflight_report(
                pdf_file,
                glossary_file,
                display_start_page,
                end_page_str,
                model,
                int(workers),
                current_task_signature,
            )
            st.session_state["preflight_report"] = report
            preflight_report = report
            preflight_ready = True
        except ValueError as e:
            st.error(str(e))
            st.session_state.pop("preflight_report", None)
            preflight_ready = False
    st.markdown("</div>", unsafe_allow_html=True)

    if preflight_ready:
        render_preflight_report(preflight_report)
    else:
        st.info("当前任务还没有完成预检，或预检结果已经过期。")

if pdf_file and show_extraction_preview:
    preview_path = save_uploaded_pdf_for_preview(pdf_file)
    preview_extractor = None
    try:
        preview_extractor = PDFExtractor(str(preview_path))
        total_preview_pages = preview_extractor.total_pages
        preview_index = min(max(int(preview_page) - 1, 0), total_preview_pages - 1)
        preview_text = preview_extractor.extract_page(preview_index)
        preview_notes = preview_extractor.get_layout_notes(preview_index)
        preview_diag = preview_extractor.get_page_diagnostics(preview_index, preview_text)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("提取预览 / 诊断")
        st.caption(
            f"PDF 共 {total_preview_pages} 页；当前预览第 {preview_index + 1} 页。"
            "这里只展示提取和排序后的文本，不会调用翻译 API。"
        )
        if preview_notes:
            st.caption("版面识别：" + "；".join(preview_notes))
        if preview_diag["risks"]:
            st.warning("风险提示：" + "；".join(preview_diag["risks"]))
        if preview_text.strip():
            st.text_area("提取文本", preview_text, height=420)
        else:
            st.warning("这一页没有提取到正文文本。可能是图片页、扫描页，或文本被页眉页脚过滤规则排除了。")
        st.markdown("</div>", unsafe_allow_html=True)
    except Exception as e:
        st.warning(f"提取预览失败：{e}")
    finally:
        if preview_extractor:
            preview_extractor.close()

if st.button("执行翻译任务", type="primary", use_container_width=True, disabled=not preflight_ready):
    if not pdf_file:
        st.error("✗ 请上传 PDF 文件")
    elif not api_key:
        st.error("✗ 请输入接口密钥")
    elif not base_url.strip():
        st.error("✗ 请输入接口地址")
    elif not model.strip():
        st.error("✗ 请输入模型名称")
    elif not formats:
        st.error("✗ 请至少选择一种输出格式")
    else:
        # Create organized directories
        upload_dir = APP_DIR / "uploads"
        output_dir = APP_DIR / "output"
        ensure_dir(upload_dir)
        ensure_dir(output_dir)

        # Save uploaded files to uploads/
        pdf_stem = safe_filename_stem(pdf_file.name)
        pdf_upload_name = f"_upload_{pdf_stem}_{uuid.uuid4().hex[:8]}.pdf"
        pdf_path = str(upload_dir / pdf_upload_name)
        with open(pdf_path, "wb") as f:
            f.write(pdf_file.getvalue())

        glossary_path = str(DEFAULT_GLOSSARY_PATH) if DEFAULT_GLOSSARY_PATH.exists() else None
        if glossary_file:
            glossary_suffix = Path(glossary_file.name).suffix.lower() or ".tsv"
            glossary_upload_name = f"_upload_{safe_filename_stem(glossary_file.name, 'glossary')}_{uuid.uuid4().hex[:8]}{glossary_suffix}"
            glossary_path = str(upload_dir / glossary_upload_name)
            with open(glossary_path, "wb") as f:
                f.write(glossary_file.getvalue())

        try:
            start_page = int(display_start_page) - 1
            display_end_page = int(end_page_str) if end_page_str.strip() else None
        except ValueError:
            st.error("结束页必须是整数，或留空表示全部。")
            st.stop()
        document_output_dir = output_dir / f"{pdf_stem}_cn"
        ensure_dir(document_output_dir)
        output_base = str(document_output_dir / f"{pdf_stem}_cn")

        # Init
        stats = TokenStats()
        extractor = PDFExtractor(pdf_path)
        total = extractor.total_pages
        try:
            start_page, end_page = normalize_page_range(start_page, display_end_page, total)
        except ValueError as e:
            st.error(str(e))
            extractor.close()
            st.stop()
        if "word" in formats and word_max_chars < word_min_chars:
            st.error("文档排版的阅读页最多字数必须大于或等于最少字数。")
            extractor.close()
            st.stop()

        glossary = load_glossary(glossary_path) if glossary_path else {}
        if glossary_path:
            glossary_source = Path(glossary_path).name
            st.info(f"📚 术语表: {glossary_source} ({len(glossary)} 条)")
        else:
            st.warning("未使用术语表。")
        translator = Translator(api_key=api_key, model=model, base_url=base_url, stats=stats)
        translator.set_glossary(glossary)

        progress_file = output_base + ".progress.json"
        progress_metadata = build_progress_metadata(
            pdf_path=pdf_path,
            glossary_path=glossary_path,
            model=model,
            provider=provider,
            base_url=base_url,
            start_page=start_page,
            end_page=end_page,
        )
        tracker = ProgressTracker(
            progress_file,
            expected_metadata=progress_metadata,
            reuse_mismatched=reuse_mismatched_progress,
        )
        if tracker.metadata_mismatches:
            st.warning(
                "检测到 progress.json 与当前设置不一致："
                + "；".join(tracker.metadata_mismatches[:3])
            )
            if tracker.ignored_existing_progress:
                st.info("已保留原 progress 文件，但本次不会复用其中的旧译文。")

        failed_from_progress = {
            p for p in tracker.get_failed_pages()
            if start_page <= p < end_page
        }
        if failed_from_progress:
            st.info(
                "进度文件中记录的失败页："
                + ", ".join(str(p + 1) for p in sorted(failed_from_progress)[:30])
            )

        try:
            retranslate_pages = parse_page_selection(retranslate_pages_str, total)
        except ValueError as e:
            st.error(f"重翻页码格式错误：{e}")
            extractor.close()
            st.stop()
        retranslate_pages = {p for p in retranslate_pages if start_page <= p < end_page}
        if retranslate_pages:
            cleared = tracker.clear_pages(retranslate_pages)
            display_pages = ", ".join(str(p + 1) for p in sorted(retranslate_pages))
            st.info(f"已标记重翻页：{display_pages}（清理 {cleared} 条旧进度）。")
        if retry_failed_pages:
            if failed_from_progress:
                pages_filter = failed_from_progress
                tracker.clear_failed_pages(pages_filter)
                st.info(
                    "本次只重试失败页："
                    + ", ".join(str(p + 1) for p in sorted(pages_filter))
                )
            else:
                pages_filter = set()
                st.warning("没有可重试的失败页。")
        else:
            pages_filter = set(range(start_page, end_page))

        # Extract
        st.info(f"📑 提取文本: {total} 页, 翻译第 {start_page + 1}-{end_page} 页")
        pages_text = {}
        page_layouts = {}
        page_diagnostics = []
        image_assets = {}
        asset_dir = str(document_output_dir / "assets")
        for pn in range(start_page, end_page):
            page_layouts[pn] = extractor.detect_page_layout(pn)
            pages_text[pn] = extractor.extract_page(pn)
            page_diagnostics.append(extractor.get_page_diagnostics(pn, pages_text[pn]))
            images = extractor.export_page_images(pn, asset_dir, pdf_stem)
            if images:
                image_assets[pn] = images
        extractor.finalize_chapters()
        toc = extractor.chapter_detector.get_toc_markdown()
        risky_pages = [item for item in page_diagnostics if item.get("risks")]
        if risky_pages:
            st.warning(
                "提取诊断发现风险页："
                + ", ".join(str(item["page"] + 1) for item in risky_pages[:30])
            )
        if image_assets:
            st.info(f"已裁出图片资源：{sum(len(v) for v in image_assets.values())} 张")

        # Translate
        st.subheader("翻译进度")
        progress_bar = st.progress(0)
        status_text = st.empty()
        metric_cols = st.columns(5)
        progress_metric = metric_cols[0].empty()
        elapsed_metric = metric_cols[1].empty()
        eta_metric = metric_cols[2].empty()
        speed_metric = metric_cols[3].empty()
        cost_metric = metric_cols[4].empty()
        pages_list = sorted(pages_filter)
        total_to_do = len(pages_list)
        pages_data = []
        prev_text = ""
        for pn in pages_list:
            text = pages_text.get(pn, "")
            pages_data.append((pn, text, prev_text[-900:] if prev_text else ""))
            context_text = extractor.get_context_text(pn)
            if context_text.strip():
                prev_text = context_text

        translation_started_at = time.time()

        def set_progress(value, text):
            try:
                progress_bar.progress(value, text=text)
            except TypeError:
                progress_bar.progress(value)

        def render_progress(completed_count, total_count, latest_page=None):
            pct = completed_count / total_count if total_count else 1.0
            elapsed = time.time() - translation_started_at
            avg_seconds = elapsed / completed_count if completed_count else None
            remaining_seconds = (
                avg_seconds * (total_count - completed_count)
                if avg_seconds is not None else None
            )
            speed = 60 / avg_seconds if avg_seconds else None
            latest_text = f" | 最新第 {latest_page + 1} 页" if latest_page is not None else ""
            progress_text = (
                f"{completed_count}/{total_count} 页 ({pct * 100:.0f}%)"
                f" | 已用 {format_duration(elapsed)}"
                f" | 剩余 {format_duration(remaining_seconds)}"
            )
            set_progress(min(pct, 1.0), progress_text)
            status_text.text(
                f"翻译中: 已完成 {completed_count}/{total_count} 页{latest_text} | "
                f"费用 ¥{stats.cost_yuan:.3f}"
            )
            progress_metric.metric("进度", f"{completed_count}/{total_count}")
            elapsed_metric.metric("已用时", format_duration(elapsed))
            eta_metric.metric("预计剩余", format_duration(remaining_seconds))
            speed_metric.metric("速度", f"{speed:.1f} 页/分钟" if speed else "估算中")
            cost_metric.metric("费用", f"¥{stats.cost_yuan:.3f}")

        def update_translation_progress(page_num, translation, completed_count, total_count):
            render_progress(completed_count, total_count, page_num)

        if total_to_do:
            render_progress(0, total_to_do)
            results = translate_batch_concurrent(
                pages_data,
                translator,
                tracker,
                max_workers=max(1, int(workers)),
                progress_callback=update_translation_progress,
            )
        else:
            results = {}

        render_progress(total_to_do, total_to_do)
        status_text.text(f"✓ 翻译完成! 总用时 {format_duration(time.time() - translation_started_at)}")
        translated_pages_sorted = sorted(
            [
                (pn, tracker.get_translation(pn))
                for pn in range(start_page, end_page)
                if tracker.get_translation(pn).strip()
            ],
            key=lambda x: x[0],
        )
        failed_pages = [
            pn + 1 for pn in sorted(tracker.get_failed_pages())
            if start_page <= pn < end_page
        ]
        risk_page_numbers = [
            item["page"] + 1 for item in page_diagnostics
            if item.get("risks")
        ]
        empty_page_numbers = [
            item["page"] + 1 for item in page_diagnostics
            if "未提取到正文" in item.get("risks", [])
        ]
        if failed_pages:
            st.warning(
                "以下页翻译失败，已记录为失败页，修复网络/API 问题后可勾选“只重试失败页”："
                + ", ".join(map(str, failed_pages[:20]))
            )
        render_recovery_action_panel(failed_pages, risk_page_numbers, empty_page_numbers)

        # Stats
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("📄 页数", f"{len(translated_pages_sorted)}")
        col_b.metric("💰 费用", f"¥{stats.cost_yuan:.3f}")
        col_c.metric("🔢 Token", f"{stats.total_tokens:,}")

        # Output & Download
        generated_files = []
        diagnostics_path = make_output_path(output_base, "_extraction_report.md")
        with open(diagnostics_path, "w", encoding="utf-8") as f:
            f.write(build_extraction_diagnostics_report(page_diagnostics, pdf_stem))
            f.write("\n")
        remember_generated_file(generated_files, diagnostics_path, "提取诊断报告")
        with open(diagnostics_path, "rb") as f:
            st.download_button(
                "📥 下载提取诊断报告",
                f,
                file_name=Path(diagnostics_path).name,
            )

        if glossary:
            report_path = make_output_path(output_base, "_glossary_report.md")
            write_glossary_report(pages_text, glossary, report_path, pdf_stem)
            remember_generated_file(generated_files, report_path, "术语命中报告")
            with open(report_path, "rb") as f:
                st.download_button(
                    "📥 下载术语命中报告",
                    f,
                    file_name=Path(report_path).name,
                )

        if "markdown" in formats:
            md_path = make_output_path(output_base, ".md")
            write_markdown_output(
                translated_pages_sorted,
                md_path,
                pdf_stem,
                toc,
                page_layouts=page_layouts,
                image_assets=image_assets,
            )
            remember_generated_file(generated_files, md_path, "纯文本稿")

            with open(md_path, "rb") as f:
                st.download_button(
                    "📥 下载纯文本稿",
                    f,
                    file_name=Path(md_path).name,
                )

        if "html" in formats:
            html_path = make_output_path(output_base, ".html")
            try:
                write_html_output(
                    translated_pages_sorted,
                    html_path,
                    pdf_stem,
                    page_layouts=page_layouts,
                    image_assets=image_assets,
                )
                remember_generated_file(generated_files, html_path, "网页排版")
                with open(html_path, "rb") as f:
                    st.download_button(
                        "📥 下载网页排版",
                        f,
                        file_name=Path(html_path).name,
                        mime="text/html",
                    )
            except Exception as e:
                st.error(f"网页排版输出失败：{e}")

        if "word" in formats:
            if not HAS_DOCX:
                st.warning("文档排版需要 python-docx，请运行：pip install python-docx")
            else:
                docx_path = make_output_path(output_base, ".docx")
                write_word_output(
                    translated_pages_sorted,
                    docx_path,
                    pdf_stem,
                    min_chars=int(word_min_chars),
                    max_chars=int(word_max_chars),
                    body_font_size=float(word_body_font_size),
                    line_spacing=float(word_line_spacing),
                    columns=int(word_columns),
                    header_left=word_header_left,
                    header_right=word_header_right or None,
                    hard_page_breaks=bool(word_hard_page_breaks),
                    source_pages_text=pages_text,
                    page_layouts=page_layouts,
                    image_assets=image_assets,
                )
                remember_generated_file(generated_files, docx_path, "文档排版")

                with open(docx_path, "rb") as f:
                    st.download_button(
                        "📥 下载文档排版",
                        f,
                        file_name=Path(docx_path).name,
                    )

        write_history_manifest(
            output_base,
            pdf_stem,
            progress_file,
            formats,
            generated_files,
            stats,
            int(workers),
            model,
            provider,
            len(translated_pages_sorted),
            failed_pages,
        )

        extractor.close()
