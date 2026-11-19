"""share/codeteam_dir_paths.py alone (D526): a DIR is itself; the repo root, in any spelling, is the lane's owned
paths from CODETEAM_OWNS, glob-expanded; the root with no owned paths is refused. cmd_test_one with it: the
zone-tool test-one tests (tests/unit/test_zone_tool_*.py, zone/tests/zone-test-one.sh).
"""
import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("codeteam_dir_paths", ROOT / "share" / "codeteam_dir_paths.py")
module = importlib.util.module_from_spec(spec)
dont_write_bytecode = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
finally:
    sys.dont_write_bytecode = dont_write_bytecode


@pytest.fixture
def repo(tmp_path):
    for rel in ("zone", "tests/unit", "share/b.py", "share/a.py", "share/c.sh"):
        path = tmp_path / rel
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")
        else:
            path.mkdir(parents=True)
    return tmp_path


def test_a_folder_is_itself_and_not_owned(repo):
    assert module.dir_paths("tests/unit", repo, {"CODETEAM_OWNS": "share/*.py"}) == [("tests/unit", False)]


@pytest.mark.parametrize("spelling", [".", "./", "zone/..", "ROOT"])
def test_the_root_in_any_spelling_is_the_owned_paths_in_entry_order(repo, spelling):
    target = str(repo) if spelling == "ROOT" else spelling
    got = module.dir_paths(target, repo, {"CODETEAM_OWNS": "tests/unit:share/*.py"})
    assert got == [("tests/unit", True), ("share/a.py", True), ("share/b.py", True)]


def test_each_entrys_matches_come_back_sorted_whatever_order_glob_gives(repo, monkeypatch):
    # glob's order is the file system's; a temp folder's is often sorted already, so glob here gives it reversed.
    real = module.glob.glob
    monkeypatch.setattr(module.glob, "glob", lambda pattern, root_dir=None: sorted(real(pattern, root_dir=root_dir),
                                                                                  reverse=True))
    got = module.dir_paths(".", repo, {"CODETEAM_OWNS": "share/*:tests/unit"})
    assert got == [("share/a.py", True), ("share/b.py", True), ("share/c.sh", True), ("tests/unit", True)]


def test_empty_entries_and_entries_matching_nothing_add_nothing(repo):
    assert module.dir_paths(".", repo, {"CODETEAM_OWNS": ":share/c.sh::missing/*:"}) == [("share/c.sh", True)]


@pytest.mark.parametrize("environ", [{}, {"CODETEAM_OWNS": ""}, {"CODETEAM_OWNS": "::"}])
def test_the_root_with_no_owned_paths_is_refused_with_the_reason(repo, environ, capsys):
    assert module.dir_paths(".", repo, environ) is None
    assert capsys.readouterr().out == ("test-one: DIR=. is the repo root, which means the lane's owned paths, and "
                                       "CODETEAM_OWNS is empty; set CODETEAM_OWNS or give DIR a folder\n")
