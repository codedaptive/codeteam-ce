"""The web deck's agent rows and wide panels, rendered through Node: one tags cell per agent row, the
focus and BUILDS splits. Layout itself (scrolling columns, track widths) is not tested here: a check of the
stylesheet's declarations is not a test (zone-tests)."""
import re

import pytest

from test_deck_web_page import BASE_UI, Elements, call_js, classes, integration_only, needs_node, snapshot


def has_token(text, fact):
    """fact in text as a whole token: no letter or digit right before or after it, so "1 running" does not pass on
    "11 running"."""
    return re.search(rf"(?<![0-9A-Za-z]){re.escape(fact)}(?![0-9A-Za-z])", text) is not None


def render_agents(sessions, scope="session", cursor=0, teams=None):
    """agents() over one vis entry per session, in team teams[i] (all in "team" when teams is None)."""
    vis = [{"id": f"team/{i}", "team": {"name": teams[i] if teams else "team"}, "session": session}
           for i, session in enumerate(sessions)]
    return Elements(call_js("agents.js", "agents", vis, 100, cursor, scope, False, False)).found


def agent_rows(elements):
    return sorted((el for el in elements if "arow" in classes(el)), key=lambda el: el["start"])


def label(row, elements):
    """An agent row's description, without its number."""
    return next(el for el in children(elements, row) if "label" in classes(el))["text"].split(": ", 1)[1]


def children(elements, parent):
    inside = [el for el in elements if parent["start"] < el["start"] < parent["start"] + len(parent["markup"])]
    return sorted((el for el in inside if not any(
        other is not el and other["start"] < el["start"] < other["start"] + len(other["markup"])
        for other in inside)), key=lambda el: el["start"])


@integration_only
@needs_node
def test_each_agent_has_one_tags_cell_after_elapsed_including_empty():
    elements = render_agents([{"name": "first", "agents": [
        {"description": "clean", "started": 10, "last_write": 20},
        {"description": "flagged", "started": 30, "last_write": 40,
         "flags": {"stalled": True, "orphan": True}},
    ]}])
    rows = sorted((el for el in elements if "arow" in classes(el)), key=lambda el: el["start"])
    assert len(rows) == 2
    for row in rows:
        cells = children(elements, row)
        tags = [cell for cell in cells if "tags" in classes(cell)]
        assert len(tags) == 1, row["markup"]
        assert tags[0]["tag"] == "span"
        elapsed = next(i for i, cell in enumerate(cells) if "num" in classes(cell) and "c-dim" in classes(cell))
        assert cells[elapsed + 1] is tags[0]
    assert next(cell for cell in children(elements, rows[0]) if "tags" in classes(cell))["text"] == ""
    badge_text = next(cell for cell in children(elements, rows[1]) if "tags" in classes(cell))["text"]
    assert "stalled " in badge_text
    assert "orphan" in badge_text


@integration_only
@needs_node
@pytest.mark.parametrize("flag", ["stalled", "waiting_on_finished_child", "orphan"])
def test_agents_section_has_tags_for_each_shown_flag(flag):
    elements = render_agents([{"name": "first", "agents": [
        {"description": "clean"}, {"description": "flagged", "flags": {flag: True}},
    ]}])
    section = next(el for el in elements if el["tag"] == "section" and "agents" in classes(el))
    assert "has-tags" in classes(section)


@integration_only
@needs_node
def test_agents_section_ignores_flags_on_unshown_sessions():
    elements = render_agents([
        {"name": "shown", "agents": [{"description": "clean"}]},
        {"name": "hidden", "agents": [{"description": "flagged", "flags": {"orphan": True}}]},
    ])
    section = next(el for el in elements if el["tag"] == "section" and "agents" in classes(el))
    assert "has-tags" not in classes(section)


@integration_only
@needs_node
def test_all_agents_rows_end_with_owner_after_tags():
    elements = render_agents([
        {"name": "first", "agents": [{"description": "clean", "started": 10}]},
        {"name": "second", "agents": [{"description": "flagged", "started": 20,
                                        "flags": {"orphan": True}}]},
    ], scope="all")
    rows = sorted((el for el in elements if "arow" in classes(el)), key=lambda el: el["start"])
    assert len(rows) == 2
    for row, owner in zip(rows, ("first", "second")):
        cells = children(elements, row)
        assert "owner" in classes(cells[-1])
        assert cells[-1]["text"] == owner
        assert "tags" in classes(cells[-2]), row["markup"]


@integration_only
@needs_node
def test_running_agents_come_first_in_start_order_then_the_last_finished_first_under_a_label():
    elements = render_agents([{"name": "first", "agents": [
        {"description": "done late", "started": 10, "last_write": 95, "finished": True},
        {"description": "runs early", "started": 20, "last_write": 90},
        {"description": "done early", "started": 30, "last_write": 35, "finished": True},
        {"description": "runs late", "started": 40, "last_write": 90, "flags": {"stalled": True}},
    ]}])
    ordered = sorted((el for el in elements if {"arow", "agroup"} & set(classes(el))), key=lambda el: el["start"])
    assert [el["text"] if "agroup" in classes(el) else label(el, elements) for el in ordered] == [
        "running · 2", "runs early", "runs late", "finished · 2", "done late", "done early"]
    assert ["done" in classes(row) for row in agent_rows(elements)] == [False, False, True, True]
    assert [row["text"].split(": ")[0][-1] for row in agent_rows(elements)] == ["1", "2", "3", "4"]


@integration_only
@needs_node
@pytest.mark.parametrize("finished", [False, True])
def test_one_group_alone_has_no_label_row(finished):
    elements = render_agents([{"name": "first", "agents": [
        {"description": "one", "started": 10, "last_write": 20, "finished": finished},
        {"description": "two", "started": 30, "last_write": 40, "finished": finished},
    ]}])
    assert [el for el in elements if "agroup" in classes(el)] == []
    assert len(agent_rows(elements)) == 2


def lane_left(row, elements):
    """The left edge, in percent, of an agent row's swimlane bar (its style's left:)."""
    lane = next(el for el in children(elements, row) if "lane" in classes(el))
    bar = next(el for el in elements if el["tag"] == "i" and lane["start"] < el["start"] < lane["start"] + len(lane["markup"]))
    return float(bar["attrs"]["style"].split("left:")[1].split("%")[0])


@integration_only
@needs_node
def test_the_time_axis_starts_no_earlier_than_six_hours_ago():
    # An agent resumed after days keeps its first start (acme's 74 h on 11-16): the axis must not stretch back to it.
    now = 100_000
    vis = [{"id": "team/0", "team": {"name": "team"}, "session": {"name": "first", "agents": [
        {"description": "resumed", "started": 0, "last_write": 99_000, "finished": True},
        {"description": "an hour old", "started": now - 3600, "last_write": 99_000},
    ]}}]
    elements = Elements(call_js("agents.js", "agents", vis, now, 0, "session", False, False)).found
    lefts = {label(row, elements): lane_left(row, elements) for row in agent_rows(elements)}
    # Six hours of axis: a start one hour ago sits five sixths along, and the older start at the left edge.
    assert lefts == {"resumed": 0.0, "an hour old": 83.33}


@integration_only
@needs_node
def test_finished_agents_show_for_three_hours_and_running_ones_stay():
    # 3 hours keeps the list short.
    now = 100_000
    vis = [{"id": "team/0", "team": {"name": "team"}, "session": {"name": "first", "agents": [
        {"description": "finished 3 h 1 m ago", "started": 80_000, "last_write": now - 10_860, "finished": True},
        {"description": "finished 2 h 59 m ago", "started": 80_000, "last_write": now - 10_740, "finished": True},
        {"description": "silent 5 h, running", "started": 80_000, "last_write": now - 18_000},
    ]}}]
    elements = Elements(call_js("agents.js", "agents", vis, now, 0, "session", False, False)).found
    assert [label(row, elements) for row in agent_rows(elements)] == ["silent 5 h, running", "finished 2 h 59 m ago"]
    head = next(el for el in elements if "ahead" in classes(el))
    assert has_token(head["text"], "1 running · 2 total")


@integration_only
@needs_node
def test_team_scope_shows_every_session_of_the_cursors_team_with_owners():
    sessions = [
        {"name": "orc-a", "agents": [{"description": "plan", "started": 10}]},
        {"name": "kong-b", "agents": [{"description": "review", "started": 20}]},
        {"name": "lane-a", "agents": [{"description": "port", "started": 30}]},
    ]
    teams = ["alpha", "beta", "alpha"]
    for cursor, shown in ((0, [("plan", "orc-a"), ("port", "lane-a")]), (1, [("review", "kong-b")])):
        elements = render_agents(sessions, scope="team", cursor=cursor, teams=teams)
        rows = agent_rows(elements)
        assert [(label(row, elements), children(elements, row)[-1]["text"]) for row in rows] == shown
        section = next(el for el in elements if el["tag"] == "section")
        assert "owners" in classes(section)
        assert f"team {teams[cursor]}" in section["text"]
    every = render_agents(sessions, scope="all", cursor=0, teams=teams)
    assert [label(row, every) for row in agent_rows(every)] == ["plan", "review", "port"]
    one = render_agents(sessions, scope="session", cursor=2, teams=teams)
    assert [label(row, one) for row in agent_rows(one)] == ["port"]
    assert "owners" not in classes(next(el for el in one if el["tag"] == "section"))


BUILDS_SNAPSHOT = {
    "queue": {
        "runner": {"state": "live", "used": 2, "budget": 4, "swap": 0.25},
        "classes": [{
            "class": "dev", "ceiling": 4,
            "running": [
                {"team": "alpha", "session": "short", "running_s": 30},
                {"team": "alpha", "session": "long", "running_s": 90},
            ],
            "queued": [
                {"position": 1, "team": "alpha", "session": "one"},
                {"position": 2, "team": "alpha", "session": "two"},
                {"position": 3, "team": "alpha", "session": "three"},
                {"position": 4, "team": "alpha", "session": "four"},
            ],
            "waits": {"n": 2, "window_h": 24, "median_s": 60, "max_s": 120},
        }],
    },
    "warms": [{"state": "held", "elapsed_s": 60, "worktree": "wt"}],
}


def split_parts(markup):
    elements = Elements(markup).found
    splits = [el for el in elements if "split" in classes(el)]
    assert len(splits) == 1
    split = splits[0]
    parts = {name: [el for el in elements if name in classes(el)
                    and split["start"] < el["start"] < split["start"] + len(split["markup"])]
             for name in ("split-l", "split-r")}
    assert all(len(part) == 1 for part in parts.values())
    return split, parts["split-l"][0], parts["split-r"][0]


@integration_only
@needs_node
def test_wide_builds_places_queued_jobs_in_right_column():
    _, left, right = split_parts(call_js("builds.js", "builds", BUILDS_SNAPSHOT, False, 1000))
    left_rows = [el for el in Elements(left["markup"]).found if "row" in classes(el)]
    right_rows = [el for el in Elements(right["markup"]).found if "row" in classes(el)]
    assert not [row for row in left_rows if row["text"].startswith("#")]
    assert [row["text"].split()[0] for row in right_rows if row["text"].startswith("#")] == ["#1", "#2", "#3", "#4"]
    assert len(right_rows) == 4


@integration_only
@needs_node
def test_wide_builds_places_running_and_summary_rows_in_left_column():
    _, left, right = split_parts(call_js("builds.js", "builds", BUILDS_SNAPSHOT, False, 1000))
    left_rows = [el["text"] for el in Elements(left["markup"]).found if "row" in classes(el)]
    right_rows = [el["text"] for el in Elements(right["markup"]).found if "row" in classes(el)]
    running = [text for text in left_rows if text.startswith("●")]
    assert len(running) == 2
    assert "long" in running[0] and "short" in running[1]
    assert any(has_token(text, "2 running") and has_token(text, "4 queued") for text in left_rows)
    assert any("budget" in text for text in left_rows)
    assert any("waits 24h" in text for text in left_rows)
    assert any("warm held" in text for text in left_rows)
    assert not any(text.startswith("●") or "budget" in text or "waits 24h" in text for text in right_rows)


@integration_only
@needs_node
def test_wide_builds_data_rows_is_taller_column():
    split, _, _ = split_parts(call_js("builds.js", "builds", BUILDS_SNAPSHOT, False, 1000))
    # Left: strip, counts, budget, chips, two running, waits, warm. Right: four queued.
    assert split["attrs"].get("data-rows") == "8"


@integration_only
@needs_node
@pytest.mark.parametrize("width", [500, 819])
def test_narrow_builds_matches_omitted_width(width):
    omitted = call_js("builds.js", "builds", BUILDS_SNAPSHOT, False)
    narrow = call_js("builds.js", "builds", BUILDS_SNAPSHOT, False, width)
    assert narrow == omitted
    assert not [el for el in Elements(narrow).found if "split" in classes(el)]
    assert not [el for el in Elements(omitted).found if "split" in classes(el)]


@integration_only
@needs_node
def test_builds_is_wide_at_820():
    split_parts(call_js("builds.js", "builds", BUILDS_SNAPSHOT, False, 820))


@integration_only
@needs_node
def test_render_deck_passes_width_to_focus():
    elements = Elements(call_js("deck.js", "renderDeck", snapshot(), {**BASE_UI, "width": 1000})).found
    focus = next(el for el in elements if el["attrs"].get("data-panel") == "focus")
    assert len([el for el in elements if "split" in classes(el)
                and focus["start"] < el["start"] < focus["start"] + len(focus["markup"])]) == 1


@integration_only
@needs_node
def test_render_deck_passes_width_to_builds():
    snap = {**snapshot(), "builds": BUILDS_SNAPSHOT}
    elements = Elements(call_js("deck.js", "renderDeck", snap, {**BASE_UI, "width": 1000})).found
    builds = next(el for el in elements if el["attrs"].get("data-panel") == "builds")
    _, _, right = split_parts(builds["markup"])
    rows = [el for el in Elements(right["markup"]).found if "row" in classes(el)]
    assert [row["text"].split()[0] for row in rows if row["text"].startswith("#")] == ["#1", "#2", "#3", "#4"]
    assert len(rows) == 4

    elements = Elements(call_js("deck.js", "renderDeck", snap, BASE_UI)).found
    builds = next(el for el in elements if el["attrs"].get("data-panel") == "builds")
    assert not [el for el in Elements(builds["markup"]).found if "split" in classes(el)]


@integration_only
@needs_node
def test_render_deck_without_width_has_no_split():
    elements = Elements(call_js("deck.js", "renderDeck", snapshot(), BASE_UI)).found
    assert not [el for el in elements if "split" in classes(el)]
