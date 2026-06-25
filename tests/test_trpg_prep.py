from core.glossary import GlossaryCandidate
from core.quality import QualityIssue, QualityReport
from core.trpg_prep import (
    build_module_structure,
    render_module_structure_markdown,
    render_prep_checklist_markdown,
    write_module_structure_json,
)


def test_build_module_structure_extracts_prep_entities():
    translations = {
        0: (
            "# 起始场景\n\n"
            "[STAT_BLOCK]\n"
            "Robyn Bullock\n"
            "STR 11 CON 10 DEX 9 INT 14 POW 16 CHA 13\n"
            "[/STAT_BLOCK]\n\n"
            "[CARD]\n"
            "一封写给特工的信。\n"
            "[/CARD]\n\n"
            "成功的 HUMINT roll 可以发现他说谎。失败损失 1D6 SAN。"
        )
    }

    structure = build_module_structure({}, translations, title="测试模组")

    assert [item.name for item in structure.headings] == ["起始场景"]
    assert structure.stat_blocks[0].name == "Robyn Bullock"
    assert structure.cards[0].name == "一封写给特工的信。"
    assert structure.rule_refs
    assert any(item.category == "核对数据" for item in structure.prep_items)
    assert any(item.category == "准备材料" for item in structure.prep_items)
    assert any(item.category == "标记规则" for item in structure.prep_items)


def test_build_module_structure_includes_quality_and_glossary_items():
    quality = QualityReport(
        issues=[
            QualityIssue(page_num=3, kind="missing", message="没有译文", detail="空页"),
        ]
    )
    candidates = [GlossaryCandidate(term="The Program", count=4, pages=[0, 2])]

    structure = build_module_structure(
        {0: "The Program appears."},
        {},
        quality_report=quality,
        glossary_candidates=candidates,
    )

    assert any(item.category == "翻译复核" and item.page_num == 3 for item in structure.prep_items)
    assert any(item.category == "术语确认" and item.title == "The Program" for item in structure.prep_items)


def test_prep_markdown_is_human_readable():
    structure = build_module_structure(
        {},
        {0: "# 标题\n\n角色需要进行 SAN test。"},
        title="备团测试",
    )

    markdown = render_prep_checklist_markdown(structure)

    assert markdown.startswith("# 备团测试")
    assert "待处理项" in markdown
    assert "标记规则" in markdown


def test_structure_markdown_lists_sections():
    structure = build_module_structure({}, {0: "# 标题"}, title="结构测试")

    markdown = render_module_structure_markdown(structure)

    assert "## 标题" in markdown
    assert "## 数据块" in markdown
    assert "第 1 页｜标题" in markdown


def test_structure_json_writes_serializable_data(tmp_path):
    structure = build_module_structure({}, {0: "# 标题"})
    output = tmp_path / "module_structure.json"

    write_module_structure_json(structure, str(output))

    assert '"headings"' in output.read_text(encoding="utf-8")
