"""Focus box detail layout at wide and narrow column widths."""
import pytest

from test_deck_web_page import Elements, call_js, classes, integration_only, needs_node


SESSION = {
    "name": "Example", "effort": "high", "role": "orc",
    "cost": {"session_usd": 1.25, "seat_today_usd": 2.50},
    "recent": {
        "tools": [
            {"name": "Read", "summary": "alpha file"},
            {"name": "Write", "summary": "beta file"},
            {"name": "Bash", "summary": "gamma command"},
            {"name": "Edit", "summary": "delta file"},
            {"name": "Search", "summary": "epsilon query"},
        ],
        "messages": [
            {"dir": "in", "peer": "A", "kind": "NOTE", "text": "first message"},
            {"dir": "out", "peer": "B", "kind": "REQUEST", "text": "second message"},
            {"dir": "in", "peer": "C", "kind": "DONE", "text": "third message"},
            {"dir": "out", "peer": "D", "kind": "NOTE", "text": "fourth message"},
            {"dir": "in", "peer": "E", "kind": "NOTE", "text": "fifth message"},
        ],
    },
}

TOOLS = ["tool Read alpha file", "tool Write beta file", "tool Bash gamma command",
         "tool Edit delta file", "tool Search epsilon query"]
MESSAGES = ["msg ← ? A NOTE first message", "msg → ? B REQUEST second message",
            "msg ← ? C DONE third message", "msg → ? D NOTE fourth message",
            "msg ← ? E NOTE fifth message"]
OMITTED = object()


def render(session=SESSION, expanded=False, width=1000):
    args = [session, {"name": "team"}, 100, expanded, False]
    if width is not OMITTED:
        args.append(width)
    return Elements(call_js("focus.js", "focus", *args)).found


def matching(elements, name, parent=None):
    return sorted((el for el in elements if name in classes(el) and
                   (parent is None or parent["start"] < el["start"] < parent["start"] + len(parent["markup"]))),
                  key=lambda el: el["start"])


def split_parts(elements):
    splits = matching(elements, "split")
    assert len(splits) == 1
    left = matching(elements, "split-l", splits[0])
    right = matching(elements, "split-r", splits[0])
    assert len(left) == len(right) == 1
    return splits[0], left[0], right[0]


def detail_texts(elements, parent):
    rows = matching(elements, "row", parent)
    assert all("detail" in classes(row) for row in rows)
    return [row["text"] for row in rows]


@integration_only
@needs_node
def test_wide_collapsed_splits_eight_left_and_balanced_recent_rows():
    elements = render()
    split, left, right = split_parts(elements)
    assert split["attrs"]["data-rows"] == "8"
    rows = matching(elements, "row", left)
    assert len(rows) == 8
    assert [row["text"].split()[0] for row in rows] == [
        "effort", "ctx", "$1.25", "cache", "tools", "turns", "mail", "flags"]
    assert detail_texts(elements, right) == [
        "tool Search epsilon query", "tool Edit delta file", "tool Bash gamma command", "tool Write beta file",
        "msg ← ? A NOTE first message", "msg → ? B REQUEST second message",
        "msg ← ? C DONE third message", "msg → ? D NOTE fourth message"]
    assert "alpha file" not in right["text"]
    assert "fifth message" not in right["text"]


@integration_only
@needs_node
@pytest.mark.parametrize(("tools", "messages", "expected"), [
    (2, 5, ["tool Write beta file", "tool Read alpha file", "msg ← ? A NOTE first message",
            "msg → ? B REQUEST second message", "msg ← ? C DONE third message",
            "msg → ? D NOTE fourth message", "msg ← ? E NOTE fifth message"]),
    (5, 1, ["tool Search epsilon query", "tool Edit delta file", "tool Bash gamma command",
            "tool Write beta file", "tool Read alpha file", "msg ← ? A NOTE first message"]),
])
def test_wide_collapsed_reassigns_unused_detail_budget(tools, messages, expected):
    session = {**SESSION, "recent": {"tools": SESSION["recent"]["tools"][:tools],
                                     "messages": SESSION["recent"]["messages"][:messages]}}
    elements = render(session)
    split, _, right = split_parts(elements)
    assert split["attrs"]["data-rows"] == "8"
    assert detail_texts(elements, right) == expected


@integration_only
@needs_node
def test_wide_expanded_shows_all_recent_and_taller_row_count():
    elements = render(expanded=True)
    split, _, right = split_parts(elements)
    assert split["attrs"]["data-rows"] == "10"
    assert detail_texts(elements, right) == [
        "tool Search epsilon query", "tool Edit delta file", "tool Bash gamma command",
        "tool Write beta file", "tool Read alpha file",
        "msg ← ? A NOTE first message", "msg → ? B REQUEST second message",
        "msg ← ? C DONE third message", "msg → ? D NOTE fourth message",
        "msg ← ? E NOTE fifth message"]


@integration_only
@needs_node
def test_wide_without_recent_shows_placeholder():
    elements = render({"name": "Empty"})
    split, _, right = split_parts(elements)
    assert split["attrs"]["data-rows"] == "8"
    assert detail_texts(elements, right) == ["nothing recent"]


@integration_only
@needs_node
@pytest.mark.parametrize("width", [500, OMITTED, None, 0], ids=["500", "omitted", "null", "zero"])
def test_narrow_collapsed_has_no_split_or_details(width):
    elements = render(width=width)
    assert matching(elements, "split") == []
    assert matching(elements, "detail") == []
    assert [row["text"].split()[0] for row in matching(elements, "row")] == [
        "effort", "ctx", "$1.25", "cache", "tools", "turns", "mail", "flags"]


@integration_only
@needs_node
@pytest.mark.parametrize("width", [500, OMITTED], ids=["500", "omitted"])
def test_narrow_expanded_preserves_detail_and_flags_order(width):
    elements = render(expanded=True, width=width)
    assert matching(elements, "split") == []
    rows = matching(elements, "row")
    assert [row["text"].split()[0] for row in rows] == [
        "effort", "ctx", "$1.25", "cache", "tools", "turns", "mail",
        "tool", "tool", "tool", "tool", "tool", "msg", "msg", "msg", "msg", "msg", "flags"]
    assert [row["text"] for row in rows[7:-1]] == TOOLS + MESSAGES
    assert all("detail" in classes(row) for row in rows[7:-1])


@integration_only
@needs_node
@pytest.mark.parametrize(("width", "wide"), [(683, False), (684, True)])
def test_focus_split_width_threshold(width, wide):
    elements = render(width=width)
    assert bool(matching(elements, "split")) is wide
