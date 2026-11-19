"""holds_cleaned_dirs stats real folder names in a temp tree (a ZIT by rule 11: it touches files)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_holds_cleaned_dirs import holds_cleaned_dirs  # noqa: E402


def test_a_tree_with_only_codegraph_holds(tmp_path):
    (tmp_path / ".codegraph").mkdir()
    assert holds_cleaned_dirs(tmp_path) is True


def test_a_tree_with_a_build_folder_holds(tmp_path):
    (tmp_path / "target").mkdir()
    assert holds_cleaned_dirs(tmp_path) is True


def test_a_tree_with_only_node_modules_does_not_hold(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "src").mkdir()
    assert holds_cleaned_dirs(tmp_path) is False


def test_a_tree_that_is_gone_does_not_hold(tmp_path):
    assert holds_cleaned_dirs(tmp_path / "gone") is False
