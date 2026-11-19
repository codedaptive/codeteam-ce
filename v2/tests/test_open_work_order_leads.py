"""Unit tests for live work-order lead selection (D590). Pure: no tree exists on disk. v1's tree helpers
(_landing_holds, _someone_inside, _last_activity) and PATROL_DEAD_MIN are faked, Path.is_dir answers True only for the
trees in EXISTING, and Path.resolve only normalizes the path's spelling (os.path.normpath), so two spellings of one
tree resolve alike."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.open_work_order_leads import open_work_order_leads  # noqa: E402
from codeteam2.team import v1  # noqa: E402

NOW = 1_000_000.0
T = object()
TREE = Path("/wo/alpha/one")
EXISTING = {"/wo/alpha/one"}


def fake_is_dir(self):
    return os.path.normpath(self) in EXISTING


def fake_resolve(self):
    return Path(os.path.normpath(self))


@pytest.fixture
def live_helpers():
    with patch.object(Path, "is_dir", fake_is_dir), patch.object(Path, "resolve", fake_resolve), \
            patch.object(v1, "PATROL_DEAD_MIN", 60), \
            patch.object(v1, "_landing_holds", return_value=False) as holds, \
            patch.object(v1, "_someone_inside", return_value=False) as inside, \
            patch.object(v1, "_last_activity", return_value=NOW - 180) as activity:
        yield holds, inside, activity


def record(tree, **fields):
    return {"wo": "wo-one", "zone": "alpha", "tree": str(tree), **fields}


def test_recent_activity_counts_as_live(live_helpers):
    assert open_work_order_leads(T, "alpha", [record(TREE)], set(), NOW) == ["wo-one"]


def test_someone_inside_counts_despite_old_activity(live_helpers):
    _, inside, activity = live_helpers
    inside.return_value = True
    activity.return_value = NOW - 7200
    assert open_work_order_leads(T, "alpha", [record(TREE)], set(), NOW) == ["wo-one"]


def test_other_lane_is_excluded_without_activity_checks(live_helpers):
    holds, inside, activity = live_helpers
    assert open_work_order_leads(T, "alpha", [record(TREE, zone="beta")], set(), NOW) == []
    holds.assert_not_called()
    inside.assert_not_called()
    activity.assert_not_called()


def test_queued_for_landing_is_excluded(live_helpers):
    assert open_work_order_leads(T, "alpha", [record(TREE, queued=True)], set(), NOW) == []


def test_held_work_order_is_excluded(live_helpers):
    assert open_work_order_leads(T, "alpha", [record(TREE, held=True)], set(), NOW) == []


@pytest.mark.parametrize("name", ["docs-update", "revert-update"])
def test_live_docs_and_revert_work_orders_count(live_helpers, name):
    assert open_work_order_leads(T, "alpha", [record(TREE, wo=name)], set(), NOW) == [name]


def test_missing_tree_is_excluded(live_helpers):
    assert open_work_order_leads(T, "alpha", [record("/wo/alpha/missing")], set(), NOW) == []


def test_skipped_resolved_tree_is_excluded(live_helpers):
    records = [record("/wo/alpha/other/../one")]
    assert open_work_order_leads(T, "alpha", records, {Path("/wo/alpha/one")}, NOW) == []


def test_landing_holds_excludes_tree(live_helpers):
    live_helpers[0].return_value = True
    assert open_work_order_leads(T, "alpha", [record(TREE)], set(), NOW) == []


def test_old_unoccupied_tree_is_excluded(live_helpers):
    live_helpers[2].return_value = NOW - 7200
    assert open_work_order_leads(T, "alpha", [record(TREE)], set(), NOW) == []


def test_activity_at_dead_threshold_is_not_recent(live_helpers):
    live_helpers[2].return_value = NOW - 3600
    assert open_work_order_leads(T, "alpha", [record(TREE)], set(), NOW) == []


def test_two_records_for_same_tree_count_once(live_helpers):
    records = [record(TREE, wo="first"), record("/wo/alpha/other/../one", wo="second")]
    assert open_work_order_leads(T, "alpha", records, set(), NOW) == ["first"]
