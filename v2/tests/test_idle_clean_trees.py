"""Pure choices of standing trees for an idle lane."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.idle_clean_trees import idle_clean_trees  # noqa: E402


LANE = Path("/x/lane")


def test_staff_has_no_trees_to_clean():
    assert idle_clean_trees("staff", [(LANE, True)], []) == []


def test_lane_git_tree_is_selected():
    assert idle_clean_trees("lane", [(LANE, True)], []) == [Path("/x/lane")]


def test_non_git_tree_is_not_selected():
    assert idle_clean_trees("lane", [(LANE, False)], []) == []


@pytest.mark.parametrize("busy", ["/x/lane", "/x/lane/.claude/worktrees/r1"], ids=["same", "descendant"])
def test_running_build_in_tree_excludes_it(busy):
    assert idle_clean_trees("lane", [(LANE, True)], [busy]) == []


@pytest.mark.parametrize("busy", [Path("/x/lane-2"), Path("/x")], ids=["prefix-sibling", "parent"])
def test_running_build_outside_tree_does_not_exclude_it(busy):
    assert idle_clean_trees("lane", [(LANE, True)], [busy]) == [Path("/x/lane")]


def test_normalized_busy_path_excludes_tree():
    assert idle_clean_trees("lane", [(LANE, True)], ["/x/other/../lane/./child"]) == []


def test_duplicates_collapse():
    assert idle_clean_trees("lane", [(LANE, True), (LANE, True)], []) == [Path("/x/lane")]


def test_selected_trees_keep_input_order():
    trees = [(Path("/x/z"), True), (Path("/x/no"), False), (Path("/x/a"), True)]
    assert idle_clean_trees("lane", iter(trees), iter(())) == [Path("/x/z"), Path("/x/a")]
