from core.timeline import (
    build_timeline_events,
    render_timeline_markdown,
    write_timeline_json,
    write_timeline_markdown,
)


def test_timeline_extracts_explicit_markers():
    events = build_timeline_events(
        {0: "D-1: The victim disappears."},
        {0: "D-1：受害者失踪。\n第二天，特工抵达。"},
    )

    assert len(events) == 2
    assert events[0].marker == "D-1"
    assert events[0].page_num == 1
    assert events[1].marker == "第二天"


def test_timeline_extracts_clock_and_day_names():
    events = build_timeline_events(
        {},
        {2: "Monday at 10:30 AM, the team reaches the motel."},
    )

    assert [event.marker for event in events] == ["Monday"]
    assert events[0].page_num == 3


def test_timeline_outputs_markdown_and_json(tmp_path):
    events = build_timeline_events({}, {0: "午夜，仪式开始。"})
    md_path = tmp_path / "timeline.md"
    json_path = tmp_path / "timeline.json"

    write_timeline_markdown(events, str(md_path), "测试")
    write_timeline_json(events, str(json_path))

    markdown = md_path.read_text(encoding="utf-8")
    assert markdown.startswith("# 测试")
    assert "场景时间线" in render_timeline_markdown(events)
    assert '"marker": "午夜"' in json_path.read_text(encoding="utf-8")

