import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share" / "claude-hooks"))
from lane_walls import Walls
from orc_package_refusal import _owner


def test_single_whole_repo_lane_is_the_fallback_owner():
    walls = Walls("orc", ".", (), {"alpha": {"path": ".", "owns": ["src/a"]}}, {})
    assert _owner(walls, ("crates/cli/src/main.rs", "crates/cli")) == "alpha"


def test_multiple_whole_repo_lanes_do_not_claim_unowned_package():
    walls = Walls("orc", ".", (), {"alpha": {"path": ".", "owns": ["src/a"]},
                                  "beta": {"path": ".", "owns": ["src/b"]}}, {})
    assert _owner(walls, ("crates/cli/src/main.rs", "crates/cli")) is None


def test_explicit_owner_wins_with_multiple_whole_repo_lanes():
    walls = Walls("orc", ".", (), {"alpha": {"path": ".", "owns": ["src/a"]},
                                  "beta": {"path": ".", "owns": ["crates/cli"]}}, {})
    assert _owner(walls, ("crates/cli/src/main.rs", "crates/cli")) == "beta"
